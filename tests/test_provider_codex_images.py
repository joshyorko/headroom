import json

import anyio
import httpx
from starlette.requests import Request

from headroom.providers.codex.images import (
    codex_image_forward_error_response,
    codex_image_url,
    handle_chatgpt_codex_images,
    normalize_codex_image_headers,
    sanitize_codex_image_response_headers,
)


def test_codex_image_url_includes_optional_query() -> None:
    assert (
        codex_image_url("generations", "client_version=0.142.0")
        == "https://chatgpt.com/backend-api/codex/images/generations?client_version=0.142.0"
    )
    assert codex_image_url("edits") == "https://chatgpt.com/backend-api/codex/images/edits"


def test_codex_image_headers_drop_proxy_only_headers_and_resolve_auth() -> None:
    headers, is_chatgpt_auth = normalize_codex_image_headers(
        {
            "Host": "localhost:8787",
            "Authorization": "Bearer token",
            "Accept-Encoding": "gzip",
            "X-Headroom-Bypass": "1",
            "ChatGPT-Account-ID": "acct",
            "Content-Type": "application/json",
        }
    )

    assert is_chatgpt_auth is True
    assert headers == {
        "Authorization": "Bearer token",
        "ChatGPT-Account-ID": "acct",
        "Content-Type": "application/json",
    }


def test_codex_image_response_headers_drop_stale_framing_case_insensitive() -> None:
    assert sanitize_codex_image_response_headers(
        {
            "Content-Encoding": "gzip",
            "Content-Length": "9999",
            "Content-Type": "application/json",
            "x-upstream": "kept",
        }
    ) == {
        "Content-Type": "application/json",
        "x-upstream": "kept",
    }


def test_codex_image_forward_error_response_shape() -> None:
    response = codex_image_forward_error_response()

    assert response.status_code == 502
    assert json.loads(response.body) == {
        "error": {
            "type": "upstream_error",
            "message": "Failed to forward Codex image request",
        }
    }


def test_codex_image_forwarding_inherits_configured_client_timeout() -> None:
    class RecordingClient:
        def __init__(self) -> None:
            self.kwargs: dict[str, object] = {}

        async def request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
            self.kwargs = kwargs
            return httpx.Response(200, json={"ok": True})

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b'{"prompt":"slow image"}', "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/images/generations",
            "query_string": b"",
            "headers": [
                (b"authorization", b"Bearer token"),
                (b"chatgpt-account-id", b"acct"),
                (b"content-type", b"application/json"),
            ],
        },
        receive,
    )
    client = RecordingClient()

    response = anyio.run(handle_chatgpt_codex_images, client, request, "generations")

    assert response is not None
    assert response.status_code == 200
    assert "timeout" not in client.kwargs
