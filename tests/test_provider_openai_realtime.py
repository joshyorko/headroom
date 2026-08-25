import asyncio
import base64
import json
import sys
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient

from headroom.providers.openai_realtime import relay_realtime_websocket
from headroom.proxy.server import ProxyConfig, create_app


def _jwt(payload: dict) -> str:
    def encode(part: dict) -> str:
        raw = json.dumps(part, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{encode({'alg': 'none', 'typ': 'JWT'})}.{encode(payload)}."


class FakeAsyncClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    async def request(self, method, url, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append((method, url, kwargs))
        return httpx.Response(
            201,
            content=b"v=0\r\no=upstream-answer",
            headers={
                "content-type": "application/sdp",
                "location": "/v1/realtime/calls/rtc_test_123",
            },
        )

    async def aclose(self) -> None:
        return None


def test_openai_realtime_call_preserves_raw_body_query_and_location() -> None:
    body = b"--codex-boundary\r\nContent-Type: application/sdp\r\n\r\nv=0\x00\r\n--codex-boundary--\r\n"

    with TestClient(create_app(ProxyConfig())) as client:
        fake = FakeAsyncClient()
        client.app.state.proxy.http_client = fake
        client.app.state.proxy.OPENAI_API_URL = "https://api.openai.test"
        client.app.state.proxy.config.openai_extra_headers = {"x-gateway-key": "configured"}
        response = client.post(
            "/v1/realtime/calls?intent=quicksilver&architecture=avas",
            content=body,
            headers={
                "authorization": "Bearer api-key",
                "content-type": "multipart/form-data; boundary=codex-boundary",
                "x-headroom-proxy-token": "must-not-leak",
            },
        )

    assert response.status_code == 201
    assert response.content == b"v=0\r\no=upstream-answer"
    assert response.headers["location"] == "/v1/realtime/calls/rtc_test_123"
    assert len(fake.calls) == 1
    method, url, kwargs = fake.calls[0]
    assert method == "POST"
    assert url == ("https://api.openai.test/v1/realtime/calls?intent=quicksilver&architecture=avas")
    assert kwargs["content"] == body
    assert kwargs["headers"]["authorization"] == "Bearer api-key"  # type: ignore[index]
    assert kwargs["headers"]["content-type"] == (  # type: ignore[index]
        "multipart/form-data; boundary=codex-boundary"
    )
    assert "host" not in kwargs["headers"]  # type: ignore[operator]
    assert "x-headroom-proxy-token" not in kwargs["headers"]  # type: ignore[operator]
    assert kwargs["headers"]["accept-encoding"] == "identity"  # type: ignore[index]
    assert kwargs["headers"]["x-gateway-key"] == "configured"  # type: ignore[index]


def test_openai_realtime_call_honors_custom_upstream_without_leaking_header(monkeypatch) -> None:
    async def safe_upstream(_url):  # type: ignore[no-untyped-def]
        return True

    monkeypatch.setattr("headroom.providers.proxy_routes.is_safe_upstream_url_async", safe_upstream)
    with TestClient(create_app(ProxyConfig())) as client:
        fake = FakeAsyncClient()
        client.app.state.proxy.http_client = fake
        response = client.post(
            "/v1/realtime/calls",
            content=b"v=0",
            headers={
                "content-type": "application/sdp",
                "x-headroom-base-url": "https://gateway.example/p/team/v1",
            },
        )

    assert response.status_code == 201
    _, url, kwargs = fake.calls[0]
    assert url == "https://gateway.example/p/team/v1/realtime/calls"
    assert "x-headroom-base-url" not in kwargs["headers"]  # type: ignore[operator]


def test_chatgpt_realtime_call_preserves_backend_json_shape() -> None:
    body = b'{"sdp":"v=0\\r\\n","session":{"type":"realtime"}}'

    with TestClient(create_app(ProxyConfig())) as client:
        fake = FakeAsyncClient()
        client.app.state.proxy.http_client = fake
        response = client.post(
            "/backend-api/codex/realtime/calls?architecture=avas",
            content=body,
            headers={
                "authorization": "Bearer chatgpt-oauth",
                "chatgpt-account-id": "acct_123",
                "content-type": "application/json",
            },
        )

    assert response.status_code == 201
    assert len(fake.calls) == 1
    method, url, kwargs = fake.calls[0]
    assert method == "POST"
    assert url == ("https://chatgpt.com/backend-api/codex/realtime/calls?architecture=avas")
    assert kwargs["content"] == body
    assert kwargs["headers"]["chatgpt-account-id"] == "acct_123"  # type: ignore[index]


def test_realtime_call_returns_bounded_502_without_leaking_exception() -> None:
    class FailingAsyncClient:
        async def request(self, method, url, **kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("secret-token-value")

        async def aclose(self) -> None:
            return None

    with TestClient(create_app(ProxyConfig())) as client:
        client.app.state.proxy.http_client = FailingAsyncClient()
        response = client.post(
            "/v1/realtime/calls",
            content=b"v=0",
            headers={"content-type": "application/sdp"},
        )

    assert response.status_code == 502
    assert response.text == "Upstream request failed."
    assert "secret-token-value" not in response.text


def test_realtime_websocket_routes_are_registered() -> None:
    app = create_app(ProxyConfig())
    websocket_paths = {
        route.path for route in app.routes if "websocket" in route.__class__.__name__.lower()
    }

    assert "/v1/realtime" in websocket_paths
    assert "/v1/live/{call_id}" in websocket_paths


def test_realtime_websocket_route_honors_custom_upstream(monkeypatch) -> None:
    seen: dict[str, str] = {}

    async def fake_relay(websocket, *, api_base_url, upstream_path, **kwargs):  # type: ignore[no-untyped-def]
        seen["api_base_url"] = api_base_url
        seen["upstream_path"] = upstream_path
        await websocket.accept()
        await websocket.close()

    monkeypatch.setattr("headroom.providers.proxy_routes.relay_realtime_websocket", fake_relay)

    async def safe_upstream(_url):  # type: ignore[no-untyped-def]
        return True

    monkeypatch.setattr("headroom.providers.proxy_routes.is_safe_upstream_url_async", safe_upstream)

    with TestClient(create_app(ProxyConfig())) as client:
        with client.websocket_connect(
            "/v1/live/rtc_123",
            headers={"x-headroom-base-url": "https://gateway.example/p/team/v1"},
        ):
            pass

    assert seen == {
        "api_base_url": "https://gateway.example/p/team/v1",
        "upstream_path": "/v1/live/rtc_123",
    }


def test_realtime_websocket_relays_query_headers_subprotocol_and_binary_frame(
    monkeypatch,
) -> None:
    connect_calls: list[tuple[str, dict[str, object]]] = []
    token = _jwt({"https://api.openai.com/auth": {"chatgpt_account_id": "acct-from-jwt"}})

    class FakeUpstream:
        subprotocol = "realtime"
        close_code = 1000
        close_reason = "done"

        def __init__(self) -> None:
            self._messages = iter([b"\x00opaque-event"])

        def __aiter__(self):  # type: ignore[no-untyped-def]
            return self

        async def __anext__(self):  # type: ignore[no-untyped-def]
            try:
                return next(self._messages)
            except StopIteration:
                raise StopAsyncIteration from None

        async def send(self, message):  # type: ignore[no-untyped-def]
            raise AssertionError(f"unexpected client frame: {message!r}")

        async def close(self) -> None:
            return None

    async def fake_connect(url, **kwargs):  # type: ignore[no-untyped-def]
        connect_calls.append((url, kwargs))
        return FakeUpstream()

    class FakeWebSocket:
        url = SimpleNamespace(query="call_id=rtc_123&intent=quicksilver")
        headers = {
            "host": "headroom.test",
            "authorization": f"Bearer {token}",
            "sec-websocket-key": "transport-owned",
        }
        scope = {"subprotocols": ["realtime"]}
        client = SimpleNamespace(host="127.0.0.1")

        def __init__(self) -> None:
            self.accepted: str | None = None
            self.frames: list[bytes] = []

        async def accept(self, subprotocol=None):  # type: ignore[no-untyped-def]
            self.accepted = subprotocol

        async def receive(self):  # type: ignore[no-untyped-def]
            await asyncio.Event().wait()

        async def send_bytes(self, value: bytes) -> None:
            self.frames.append(value)

        async def send_text(self, value: str) -> None:
            raise AssertionError(f"expected binary frame, got {value!r}")

        async def close(self, code=1000, reason=None):  # type: ignore[no-untyped-def]
            return None

    monkeypatch.setitem(sys.modules, "websockets", SimpleNamespace(connect=fake_connect))
    websocket = FakeWebSocket()

    asyncio.run(
        relay_realtime_websocket(
            websocket,  # type: ignore[arg-type]
            api_base_url="https://api.openai.test/v1",
            upstream_path="/v1/realtime",
            extra_headers={"x-gateway-key": "configured"},
        )
    )

    assert websocket.accepted == "realtime"
    assert websocket.frames == [b"\x00opaque-event"]
    assert len(connect_calls) == 1
    url, kwargs = connect_calls[0]
    assert url == ("wss://api.openai.test/v1/realtime?call_id=rtc_123&intent=quicksilver")
    assert kwargs["subprotocols"] == ["realtime"]
    assert kwargs["additional_headers"] == {
        "authorization": f"Bearer {token}",
        "ChatGPT-Account-ID": "acct-from-jwt",
        "x-gateway-key": "configured",
    }


def test_realtime_websocket_url_preserves_custom_upstream_prefix() -> None:
    from headroom.providers.openai_realtime import openai_realtime_websocket_url

    assert (
        openai_realtime_websocket_url(
            "https://gateway.example/p/team/v1",
            "/v1/live/rtc_123",
            "intent=quicksilver",
        )
        == "wss://gateway.example/p/team/v1/live/rtc_123?intent=quicksilver"
    )


def test_realtime_websocket_rejects_remote_client_without_proxy_token(monkeypatch) -> None:
    async def unexpected_connect(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("unauthorized websocket must not connect upstream")

    class FakeWebSocket:
        url = SimpleNamespace(query="call_id=rtc_123")
        headers = {"authorization": "Bearer chatgpt-oauth"}
        scope = {"subprotocols": []}
        client = SimpleNamespace(host="198.51.100.10")

        def __init__(self) -> None:
            self.closed: tuple[int, str] | None = None

        async def close(self, code=1000, reason=None):  # type: ignore[no-untyped-def]
            self.closed = (code, reason)

    monkeypatch.setitem(sys.modules, "websockets", SimpleNamespace(connect=unexpected_connect))
    websocket = FakeWebSocket()

    asyncio.run(
        relay_realtime_websocket(
            websocket,  # type: ignore[arg-type]
            api_base_url="https://api.openai.test",
            upstream_path="/v1/realtime",
            proxy_token="headroom-secret",
        )
    )

    assert websocket.closed == (1008, "unauthorized")


def test_realtime_websocket_rejects_cross_origin_before_upstream_connect(monkeypatch) -> None:
    async def unexpected_connect(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("cross-origin websocket must not connect upstream")

    class FakeWebSocket:
        url = SimpleNamespace(query="")
        headers = {"origin": "https://attacker.example"}
        scope = {"subprotocols": []}
        client = SimpleNamespace(host="127.0.0.1")

        def __init__(self) -> None:
            self.closed: tuple[int, str] | None = None

        async def close(self, code=1000, reason=None):  # type: ignore[no-untyped-def]
            self.closed = (code, reason)

    monkeypatch.setitem(sys.modules, "websockets", SimpleNamespace(connect=unexpected_connect))
    websocket = FakeWebSocket()

    asyncio.run(
        relay_realtime_websocket(
            websocket,  # type: ignore[arg-type]
            api_base_url="https://api.openai.test",
            upstream_path="/v1/realtime",
        )
    )

    assert websocket.closed == (1008, "origin not allowed")
