"""Opaque OpenAI Realtime WebRTC call and sideband passthrough."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
import os
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from starlette.requests import ClientDisconnect

from headroom.providers.codex.endpoints import codex_backend_url
from headroom.providers.codex.runtime import resolve_codex_routing
from headroom.proxy.handlers.openai import _is_allowed_websocket_origin
from headroom.proxy.helpers import _strip_internal_headers, merge_extra_headers
from headroom.proxy.loopback_guard import is_loopback_host

logger = logging.getLogger("headroom.providers.openai.realtime")

_HOP_BY_HOP_HEADERS = {
    "connection",
    "content-length",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
_WEBSOCKET_HANDSHAKE_HEADERS = {
    "sec-websocket-accept",
    "sec-websocket-extensions",
    "sec-websocket-key",
    "sec-websocket-protocol",
    "sec-websocket-version",
}


def normalize_realtime_headers(
    headers: Mapping[str, str], *, websocket: bool = False
) -> dict[str, str]:
    """Remove transport-owned headers while preserving auth and Codex metadata."""
    excluded = _HOP_BY_HOP_HEADERS | (_WEBSOCKET_HANDSHAKE_HEADERS if websocket else set())
    return {name: value for name, value in headers.items() if name.lower() not in excluded}


def openai_realtime_call_url(api_base_url: str, query: str = "") -> str:
    base = api_base_url.rstrip("/")
    url = f"{base}/realtime/calls" if base.endswith("/v1") else f"{base}/v1/realtime/calls"
    return f"{url}?{query}" if query else url


async def handle_realtime_call(
    http_client: Any,
    request: Request,
    *,
    api_base_url: str,
    chatgpt_backend: bool,
    extra_headers: dict[str, str] | None = None,
    config: Any = None,
    custom_upstream: bool = False,
) -> Response:
    """Relay a realtime call without decoding its SDP, multipart, or JSON body."""
    try:
        body = await request.body()
    except ClientDisconnect:
        return Response(status_code=204)

    upstream_url = (
        codex_backend_url("/realtime/calls", request.url.query)
        if chatgpt_backend
        else openai_realtime_call_url(api_base_url, request.url.query)
    )
    try:
        request_headers = normalize_realtime_headers(dict(request.headers.items()))
        if chatgpt_backend:
            request_headers = resolve_codex_routing(request_headers).headers
        request_headers["accept-encoding"] = "identity"
        request_headers = merge_extra_headers(
            _strip_internal_headers(request_headers),
            extra_headers,
            upstream_url=upstream_url if custom_upstream else None,
            config=config,
        )
        upstream = await http_client.request(
            "POST",
            upstream_url,
            headers=request_headers,
            content=body,
            timeout=120.0,
        )
    except Exception:
        logger.exception("Realtime call passthrough failed")
        return Response(content="Upstream request failed.", status_code=502)

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=normalize_realtime_headers(dict(upstream.headers)),
    )


def openai_realtime_websocket_url(api_base_url: str, path: str, query: str = "") -> str:
    base = urlsplit(api_base_url)
    scheme = "wss" if base.scheme == "https" else "ws"
    base_path = base.path.rstrip("/")
    if base_path.endswith("/v1") and path.startswith("/v1/"):
        upstream_path = f"{base_path}{path.removeprefix('/v1')}"
    elif base_path:
        upstream_path = f"{base_path}{path}"
    else:
        upstream_path = path
    url = urlunsplit((scheme, base.netloc, upstream_path, query, ""))
    return url


async def relay_realtime_websocket(
    websocket: WebSocket,
    *,
    api_base_url: str,
    upstream_path: str,
    proxy_token: str | None = None,
    extra_headers: dict[str, str] | None = None,
    config: Any = None,
    custom_upstream: bool = False,
) -> None:
    """Relay realtime sideband frames without interpreting their contents."""
    import websockets

    inbound_headers = dict(websocket.headers.items())
    if not _is_allowed_websocket_origin(inbound_headers):
        await websocket.close(code=1008, reason="origin not allowed")
        return

    expected_token = proxy_token or os.environ.get("HEADROOM_PROXY_TOKEN") or None
    client = getattr(websocket, "client", None)
    client_host = getattr(client, "host", None) if client is not None else None
    if expected_token and not is_loopback_host(client_host):
        provided = inbound_headers.get("x-headroom-proxy-token")
        if not provided:
            auth = inbound_headers.get("authorization", "")
            provided = auth[7:].strip() if auth.lower().startswith("bearer ") else None
        if provided is None or not hmac.compare_digest(provided, expected_token):
            await websocket.close(code=1008, reason="unauthorized")
            return

    upstream_url = openai_realtime_websocket_url(
        api_base_url,
        upstream_path,
        websocket.url.query,
    )
    headers = normalize_realtime_headers(inbound_headers, websocket=True)
    headers = resolve_codex_routing(headers).headers
    headers = merge_extra_headers(
        _strip_internal_headers(headers),
        extra_headers,
        upstream_url=upstream_url if custom_upstream else None,
        config=config,
    )
    subprotocols = list(websocket.scope.get("subprotocols", [])) or None

    try:
        upstream = await websockets.connect(
            upstream_url,
            additional_headers=headers,
            subprotocols=subprotocols,
            open_timeout=30,
            close_timeout=10,
            ping_interval=20,
            ping_timeout=None,
            max_size=None,
        )
    except Exception:
        logger.exception("Realtime websocket upstream connection failed")
        await websocket.close(code=1014, reason="Upstream connection failed")
        return

    async def client_to_upstream() -> None:
        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    await upstream.close(
                        code=message.get("code", 1000),
                        reason=message.get("reason") or "",
                    )
                    return
                if message.get("bytes") is not None:
                    await upstream.send(message["bytes"])
                elif message.get("text") is not None:
                    await upstream.send(message["text"])
        except WebSocketDisconnect:
            return

    async def upstream_to_client() -> None:
        async for message in upstream:
            if isinstance(message, bytes):
                await websocket.send_bytes(message)
            else:
                await websocket.send_text(message)
        await websocket.close(
            code=getattr(upstream, "close_code", None) or 1000,
            reason=getattr(upstream, "close_reason", None) or "",
        )

    try:
        selected_subprotocol = getattr(upstream, "subprotocol", None)
        await websocket.accept(subprotocol=selected_subprotocol)
        tasks = {
            asyncio.create_task(client_to_upstream()),
            asyncio.create_task(upstream_to_client()),
        }
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*done, *pending, return_exceptions=True)
    finally:
        with contextlib.suppress(Exception):
            await upstream.close()
        with contextlib.suppress(Exception):
            await websocket.close()
