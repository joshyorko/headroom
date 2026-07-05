import asyncio
import base64
import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import anyio
import pytest
from fastapi import Request

from headroom.proxy.handlers.openai import (
    OpenAIHandlerMixin,
    _apply_openai_responses_output_shaper,
    _estimate_openai_responses_output_shaper_input_tokens,
    _extract_responses_usage,
    _is_allowed_websocket_origin,
    _openai_responses_output_shaper_savings_label,
    _openai_responses_output_shaper_seed,
    _openai_responses_unit_cache_key,
    _openai_responses_ws_output_shaper_session_key,
    _resolve_codex_routing_headers,
)
from headroom.proxy.outcome import RequestOutcome


def _jwt(payload: dict) -> str:
    header = {"alg": "none", "typ": "JWT"}

    def encode(part: dict) -> str:
        raw = json.dumps(part, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return f"{encode(header)}.{encode(payload)}."


def test_resolve_codex_routing_prefers_explicit_header():
    headers, is_chatgpt = _resolve_codex_routing_headers(
        {
            "Authorization": "Bearer sk-test",
            "ChatGPT-Account-ID": "acct-explicit",
        }
    )

    assert is_chatgpt is True
    assert headers["ChatGPT-Account-ID"] == "acct-explicit"


def test_resolve_codex_routing_derives_account_id_from_oauth_jwt():
    token = _jwt(
        {
            "https://api.openai.com/auth": {
                "chatgpt_account_id": "acct-from-jwt",
            }
        }
    )

    headers, is_chatgpt = _resolve_codex_routing_headers(
        {
            "authorization": f"Bearer {token}",
        }
    )

    assert is_chatgpt is True
    assert headers["ChatGPT-Account-ID"] == "acct-from-jwt"


def test_resolve_codex_routing_leaves_regular_openai_bearer_tokens_unchanged():
    token = _jwt({"aud": ["https://api.openai.com/v1"]})

    headers, is_chatgpt = _resolve_codex_routing_headers(
        {
            "authorization": f"Bearer {token}",
        }
    )

    assert is_chatgpt is False
    assert "ChatGPT-Account-ID" not in headers


def test_resolve_codex_routing_returns_none_without_bearer_auth():
    headers, is_chatgpt = _resolve_codex_routing_headers({})

    assert is_chatgpt is False
    assert headers == {}


def test_resolve_codex_routing_ignores_non_jwt_bearer_tokens():
    headers, is_chatgpt = _resolve_codex_routing_headers(
        {
            "authorization": "Bearer not-a-jwt",
        }
    )

    assert is_chatgpt is False
    assert headers["authorization"] == "Bearer not-a-jwt"


def test_resolve_codex_routing_ignores_invalid_jwt_payloads():
    invalid_payload = base64.urlsafe_b64encode(b"not-json").decode("ascii").rstrip("=")
    token = f"test-header.{invalid_payload}.signature"

    headers, is_chatgpt = _resolve_codex_routing_headers(
        {
            "authorization": f"Bearer {token}",
        }
    )

    assert is_chatgpt is False
    assert headers["authorization"] == f"Bearer {token}"


def test_openai_responses_unit_cache_key_includes_target_ratio() -> None:
    unit = SimpleNamespace(
        text="large tool output",
        provider="openai",
        endpoint="responses",
        role="tool",
        item_type="function_call_output",
        cache_zone="live",
        mutable=True,
        min_bytes=100,
        context=None,
        question=None,
        bias=None,
        metadata={},
    )

    default_key = _openai_responses_unit_cache_key(unit, model="gpt-5.4")
    aggressive_key = _openai_responses_unit_cache_key(
        unit,
        model="gpt-5.4",
        target_ratio=0.10,
    )
    balanced_key = _openai_responses_unit_cache_key(
        unit,
        model="gpt-5.4",
        target_ratio=0.50,
    )

    assert aggressive_key != default_key
    assert aggressive_key != balanced_key


class _DummyMetrics:
    async def record_request(self, **kwargs):  # noqa: ANN003
        return None

    async def record_failed(self, **kwargs):  # noqa: ANN003
        return None


class _DummyTokenizer:
    def count_messages(self, messages):
        return len(messages)


class _ResponseStub:
    status_code = 200
    headers = {"content-type": "application/json", "content-length": "42"}
    content = b'{"id":"resp_123","output":[{"type":"message"}]}'

    def json(self):
        return {"usage": {"input_tokens": 2, "output_tokens": 1}}


class _DummyOpenAIHandler(OpenAIHandlerMixin):
    OPENAI_API_URL = "https://api.openai.com"

    def __init__(self) -> None:
        self.rate_limiter = None
        self.metrics = _DummyMetrics()
        self.config = SimpleNamespace(
            optimize=False,
            retry_max_attempts=3,
            retry_base_delay_ms=10,
            retry_max_delay_ms=50,
            connect_timeout_seconds=10,
        )
        self.usage_reporter = None
        self.openai_provider = SimpleNamespace(get_context_limit=lambda model: 128_000)
        self.openai_pipeline = SimpleNamespace(apply=MagicMock())
        self.anthropic_backend = None
        self.cost_tracker = None
        self.memory_handler = None
        # PR-A6 wires session-sticky `OpenAI-Beta` merging into the
        # responses HTTP handler — it reads `compute_session_id` to key
        # the SessionBetaTracker. The routing tests don't exercise the
        # tracker semantics themselves, so a fixed-id stub is enough.
        self.session_tracker_store = SimpleNamespace(
            compute_session_id=lambda *a, **k: "sess-openai-1",
        )
        self.captured_request: tuple[str, str, dict, dict] | None = None
        self.captured_stream_request: tuple[str, dict, dict] | None = None

    async def _next_request_id(self) -> str:
        return "req-1"

    def _extract_tags(self, headers: dict[str, str]) -> dict[str, str]:
        return {}

    async def _observe_traffic_for_learning(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return None

    async def _retry_request(self, method: str, url: str, headers: dict, body: dict):
        self.captured_request = (method, url, headers, body)
        return _ResponseStub()

    async def _run_compression_in_executor(self, fn, *, timeout: float):
        # Test stub for HeadroomProxy._run_compression_in_executor.
        # The real implementation runs `fn` on a bounded thread pool with
        # a wall-clock timeout; tests just need the callable invoked
        # synchronously so MagicMock call_count assertions fire.
        return fn()

    async def _record_request_outcome(self, outcome) -> None:
        # Test stub: delegates to the production funnel so wire shape
        # matches HeadroomProxy._record_request_outcome.
        from headroom.proxy.outcome import emit_request_outcome

        await emit_request_outcome(self, outcome)

    async def _stream_response(
        self,
        url: str,
        headers: dict,
        body: dict,
        provider: str,
        model: str,
        request_id: str,
        original_tokens: int,
        optimized_tokens: int,
        tokens_saved: int,
        transforms_applied: list[str],
        tags: dict[str, str],
        optimization_latency: float,
        memory_user_id: str | None = None,
        **kwargs,
    ):
        self.captured_stream_request = (url, headers, body)
        return SimpleNamespace(
            status_code=200,
            url=url,
            headers=headers,
            body=body,
            memory_user_id=memory_user_id,
        )


def _build_request(body: dict, headers: dict[str, str]) -> Request:
    payload = json.dumps(body).encode("utf-8")

    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/v1/responses",
        "raw_path": b"/v1/responses",
        "query_string": b"",
        "headers": [
            (key.lower().encode("utf-8"), value.encode("utf-8")) for key, value in headers.items()
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 443),
    }
    return Request(scope, receive)


def test_handle_openai_responses_routes_chatgpt_auth_to_backend_api(monkeypatch):
    token = _jwt(
        {
            "https://api.openai.com/auth": {
                "chatgpt_account_id": "acct-from-jwt",
            }
        }
    )
    request = _build_request(
        {"model": "gpt-5.4", "input": "hello"},
        {"Authorization": f"Bearer {token}"},
    )
    handler = _DummyOpenAIHandler()

    monkeypatch.setattr("headroom.tokenizers.get_tokenizer", lambda model: _DummyTokenizer())

    response = anyio.run(handler.handle_openai_responses, request)

    assert handler.captured_request is not None
    method, url, headers, body = handler.captured_request
    assert method == "POST"
    assert url == "https://chatgpt.com/backend-api/codex/responses"
    assert headers["ChatGPT-Account-ID"] == "acct-from-jwt"
    assert body["input"] == "hello"
    assert response.status_code == 200


def test_handle_openai_responses_chatgpt_codex_timeout_fails_open(monkeypatch):
    token = _jwt(
        {
            "https://api.openai.com/auth": {
                "chatgpt_account_id": "acct-from-jwt",
            }
        }
    )
    request = _build_request(
        {"model": "gpt-5.4", "input": "large context"},
        {"Authorization": f"Bearer {token}"},
    )
    handler = _DummyOpenAIHandler()
    handler.config.optimize = True

    async def timeout_compression(*args, **kwargs):  # noqa: ANN002, ANN003
        raise asyncio.TimeoutError()

    handler._compress_openai_responses_payload_in_executor = timeout_compression
    monkeypatch.setattr("headroom.tokenizers.get_tokenizer", lambda model: _DummyTokenizer())

    response = anyio.run(handler.handle_openai_responses, request)

    assert response.status_code == 200
    assert handler.captured_request is not None
    method, url, headers, body = handler.captured_request
    assert method == "POST"
    assert url == "https://chatgpt.com/backend-api/codex/responses"
    assert body["input"] == "large context"


def test_handle_openai_responses_routes_api_key_auth_direct_to_openai(monkeypatch):
    request = _build_request(
        {"model": "gpt-4o-mini", "input": "hello"},
        {"Authorization": "Bearer sk-test"},
    )
    handler = _DummyOpenAIHandler()

    monkeypatch.setattr("headroom.tokenizers.get_tokenizer", lambda model: _DummyTokenizer())

    response = anyio.run(handler.handle_openai_responses, request)

    assert handler.captured_request is not None
    method, url, headers, body = handler.captured_request
    assert method == "POST"
    assert url == "https://api.openai.com/v1/responses"
    assert headers.get("ChatGPT-Account-ID") is None
    assert body["input"] == "hello"
    assert response.status_code == 200


def test_handle_openai_responses_stream_skips_python_compression(monkeypatch):
    """PR-C5: Python no longer compresses /v1/responses (Rust handles it
    natively). The streaming forward path must still fire — only the
    Python compression dispatch is retired."""
    request = _build_request(
        {
            "model": "gpt-5.4",
            "stream": True,
            "instructions": "Keep it short",
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "hello"}],
                }
            ],
        },
        {"Authorization": "Bearer sk-test"},
    )
    handler = _DummyOpenAIHandler()
    handler.config.optimize = True

    monkeypatch.setattr("headroom.tokenizers.get_tokenizer", lambda model: _DummyTokenizer())

    response = anyio.run(handler.handle_openai_responses, request)

    assert response.status_code == 200
    assert handler.captured_stream_request is not None
    assert handler.openai_pipeline.apply.call_count == 0
    assert handler.captured_stream_request[2]["stream"] is True


def test_handle_openai_responses_memory_timeout_fails_open(monkeypatch):
    class _SlowMemoryHandler:
        def __init__(self):
            self.config = SimpleNamespace(inject_context=True, inject_tools=False)

        async def search_and_format_context(self, memory_user_id, messages, **_kwargs):
            return "should not be used"

        def has_memory_tool_calls(self, response, provider):
            return False

    async def _timeout_wait_for(awaitable, timeout):
        close = getattr(awaitable, "close", None)
        if callable(close):
            close()
        raise TimeoutError

    request = _build_request(
        {"model": "gpt-5.4", "input": "hello"},
        {"Authorization": "Bearer sk-test", "x-headroom-user-id": "user-1"},
    )
    handler = _DummyOpenAIHandler()
    handler.memory_handler = _SlowMemoryHandler()

    monkeypatch.setattr("headroom.tokenizers.get_tokenizer", lambda model: _DummyTokenizer())
    monkeypatch.setattr("headroom.proxy.handlers.openai.asyncio.wait_for", _timeout_wait_for)

    response = anyio.run(handler.handle_openai_responses, request)

    assert response.status_code == 200
    assert handler.captured_request is not None
    _, _, _, body = handler.captured_request
    assert body.get("instructions") is None


def test_codex_responses_timeout_fails_open_in_standalone_proxy(monkeypatch):
    """Codex users running only the proxy still get fail-open on timeout."""
    request = _build_request(
        {
            "model": "gpt-5.4",
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": "call-1",
                    "output": "large tool output",
                }
            ],
        },
        {"Authorization": "Bearer sk-test", "x-client": "codex"},
    )
    handler = _DummyOpenAIHandler()
    handler.config.optimize = True

    monkeypatch.setattr("headroom.tokenizers.get_tokenizer", lambda model: _DummyTokenizer())
    monkeypatch.setattr(
        handler,
        "_compress_openai_responses_payload",
        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError()),
    )

    response = anyio.run(handler.handle_openai_responses, request)

    assert response.status_code == 200
    assert handler.captured_request is not None
    _, url, _, body = handler.captured_request
    assert url == "https://api.openai.com/v1/responses"
    assert body["input"][0]["output"] == "large tool output"


class _DummyWebSocket:
    def __init__(self, headers: dict[str, str]):
        self.headers = headers
        self.accepted_subprotocol = None
        self.closed = False
        self.close_code = None
        self.close_reason = None

    async def accept(self, subprotocol=None, headers=None):
        self.accepted_subprotocol = subprotocol

    async def close(self, code=1000, reason=None):
        self.closed = True
        self.close_code = code
        self.close_reason = reason


def test_websocket_origin_policy_allows_native_clients_without_origin(monkeypatch):
    monkeypatch.delenv("HEADROOM_WS_ORIGINS", raising=False)
    monkeypatch.delenv("HEADROOM_CORS_ORIGINS", raising=False)

    assert _is_allowed_websocket_origin({"authorization": "Bearer token"}) is True


def test_websocket_origin_policy_allows_loopback_origins_by_default(monkeypatch):
    monkeypatch.delenv("HEADROOM_WS_ORIGINS", raising=False)
    monkeypatch.delenv("HEADROOM_CORS_ORIGINS", raising=False)

    assert _is_allowed_websocket_origin({"origin": "http://localhost:3000"}) is True
    assert _is_allowed_websocket_origin({"origin": "https://127.0.0.1:8787"}) is True


def test_websocket_origin_policy_requires_config_for_remote_origins(monkeypatch):
    monkeypatch.delenv("HEADROOM_WS_ORIGINS", raising=False)
    monkeypatch.delenv("HEADROOM_CORS_ORIGINS", raising=False)

    assert _is_allowed_websocket_origin({"origin": "https://remote.example"}) is False
    assert _is_allowed_websocket_origin({"origin": "http://"}) is False


def test_websocket_origin_policy_can_be_pinned_with_env(monkeypatch):
    monkeypatch.setenv("HEADROOM_WS_ORIGINS", "https://dash.example.com")
    monkeypatch.delenv("HEADROOM_CORS_ORIGINS", raising=False)

    assert _is_allowed_websocket_origin({"origin": "https://dash.example.com"}) is True
    assert _is_allowed_websocket_origin({"origin": "http://localhost:3000"}) is False


def test_handle_openai_responses_ws_resolves_codex_routing_headers():
    class SentinelError(RuntimeError):
        pass

    handler = _DummyOpenAIHandler()
    websocket = _DummyWebSocket({"authorization": "Bearer token"})

    with patch.dict(sys.modules, {"websockets": MagicMock()}):
        with patch(
            "headroom.proxy.handlers.openai._resolve_codex_routing_headers",
            side_effect=SentinelError("resolved"),
        ):
            with pytest.raises(SentinelError, match="resolved"):
                anyio.run(handler.handle_openai_responses_ws, websocket)

def test_openai_responses_output_shaper_reaches_upstream_body(monkeypatch, caplog):
    from headroom.proxy.output_shaper import steering_text

    monkeypatch.setenv("HEADROOM_OUTPUT_SHAPER", "1")
    monkeypatch.setenv("HEADROOM_VERBOSITY_LEVEL", "3")
    caplog.set_level("INFO", logger="headroom.proxy")
    handler = _DummyOpenAIHandler()
    request = _build_request(
        {
            "model": "gpt-5",
            "instructions": "Follow project rules.",
            "input": "Fix failing test.",
        },
        {"Authorization": "Bearer test"},
    )

    response = anyio.run(handler.handle_openai_responses, request)

    assert response.status_code == 200
    assert handler.captured_request is not None
    _, _, _, body = handler.captured_request
    assert body["instructions"].startswith("Follow project rules.\n\n")
    assert steering_text(3) in body["instructions"]
    assert str(body).count("<headroom_output_shaping>") == 1
    assert "output_shaper:stratum:" in caplog.text
    assert "output_shaper:verbosity:L3" in caplog.text


def test_openai_responses_output_shaper_holdout_control_skips_shape(monkeypatch, caplog):
    monkeypatch.setenv("HEADROOM_OUTPUT_SHAPER", "1")
    monkeypatch.setenv("HEADROOM_OUTPUT_HOLDOUT", "1")
    caplog.set_level("INFO", logger="headroom.proxy")

    handler = _DummyOpenAIHandler()
    request = _build_request(
        {
            "model": "gpt-5",
            "instructions": "Follow project rules.",
            "input": "Fix failing test.",
        },
        {"Authorization": "Bearer test"},
    )

    response = anyio.run(handler.handle_openai_responses, request)

    assert response.status_code == 200
    assert handler.captured_request is not None
    _, _, _, body = handler.captured_request
    assert body["instructions"] == "Follow project rules."
    assert "<headroom_output_shaping>" not in str(body)
    assert "decision=skipped_holdout_control" in caplog.text
    assert "output_shaper:control:" in caplog.text


def test_openai_responses_holdout_arm_ignores_current_turn_input(monkeypatch):
    monkeypatch.setenv("HEADROOM_OUTPUT_HOLDOUT", "0.5")
    first = {
        "model": "gpt-5",
        "instructions": "Follow project rules.",
        "input": "Fix failing test A.",
    }
    second = {
        "model": "gpt-5",
        "instructions": "Follow project rules.",
        "input": "Completely different turn B.",
    }

    first_label, first_arm, first_stratum = _openai_responses_output_shaper_savings_label(
        first,
        model="gpt-5",
        input_tokens=128,
        session_key="session-123",
    )
    second_label, second_arm, second_stratum = _openai_responses_output_shaper_savings_label(
        second,
        model="gpt-5",
        input_tokens=128,
        session_key="session-123",
    )

    assert first_arm == second_arm
    assert first_stratum == second_stratum
    assert first_label == second_label


def test_openai_responses_holdout_seed_ignores_mutable_instructions_with_session_key():
    first = {
        "model": "gpt-5",
        "instructions": "Initial project rules.",
        "input": "Fix failing test A.",
    }
    second = {
        "model": "gpt-5",
        "instructions": "Injected memory plus different current instructions.",
        "input": "Completely different turn B.",
    }

    assert _openai_responses_output_shaper_seed(
        first,
        session_key="conversation-123",
    ) == _openai_responses_output_shaper_seed(
        second,
        session_key="conversation-123",
    )


def test_openai_responses_holdout_seed_uses_instructions_without_session_key():
    first = {"model": "gpt-5", "instructions": "Rules A.", "input": "same"}
    second = {"model": "gpt-5", "instructions": "Rules B.", "input": "same"}

    assert _openai_responses_output_shaper_seed(first) != _openai_responses_output_shaper_seed(
        second
    )


def test_openai_responses_ws_shaper_session_key_survives_reconnects_and_mutable_headers():
    first_headers = {
        "x-headroom-session-id": "conversation-123",
        "user-agent": "codex/1",
        "authorization": "Bearer first",
    }
    reconnect_headers = {
        "x-headroom-session-id": "conversation-123",
        "user-agent": "codex/2",
        "authorization": "Bearer changed",
    }

    assert _openai_responses_ws_output_shaper_session_key(
        first_headers,
        client="codex",
        project="headroom",
    ) == _openai_responses_ws_output_shaper_session_key(
        reconnect_headers,
        client="codex",
        project="headroom",
    )


def test_openai_responses_output_shaper_fail_open(monkeypatch, caplog):
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setenv("HEADROOM_OUTPUT_SHAPER", "1")
    monkeypatch.setattr(
        "headroom.proxy.handlers.openai._openai_responses_output_shaper_savings_label",
        boom,
    )
    caplog.set_level("ERROR", logger="headroom.proxy")
    body = {"model": "gpt-5", "instructions": "Rules.", "input": "Hello"}
    transforms: list[str] = []

    _apply_openai_responses_output_shaper(
        body,
        model="gpt-5",
        input_tokens=42,
        transforms_applied=transforms,
        request_id="req-1",
        endpoint="responses_http",
        session_key="session-123",
    )

    assert body == {"model": "gpt-5", "instructions": "Rules.", "input": "Hello"}
    assert transforms == []
    assert "decision=error_fail_open" in caplog.text


def test_openai_responses_output_shaper_fail_open_after_partial_mutation_is_transactional(
    monkeypatch, caplog
):
    def mutate_then_boom(body, settings):
        body["instructions"] = "partially mutated"
        raise RuntimeError("boom")

    monkeypatch.setenv("HEADROOM_OUTPUT_SHAPER", "1")
    monkeypatch.setattr(
        "headroom.proxy.output_shaper.shape_openai_responses_request",
        mutate_then_boom,
    )
    caplog.set_level("ERROR", logger="headroom.proxy")
    body = {"model": "gpt-5", "instructions": "Rules.", "input": "Hello"}
    transforms: list[str] = []

    _apply_openai_responses_output_shaper(
        body,
        model="gpt-5",
        input_tokens=42,
        transforms_applied=transforms,
        request_id="req-1",
        endpoint="responses_http",
        session_key="session-123",
    )

    assert body == {"model": "gpt-5", "instructions": "Rules.", "input": "Hello"}
    assert transforms == []
    assert "decision=error_fail_open" in caplog.text


def test_codex_ws_output_shaper_estimator_uses_tokenizer_exact_count(monkeypatch):
    seen_messages = []

    class ExactTokenizer:
        def count_messages(self, messages):
            seen_messages.extend(messages)
            return 123

    monkeypatch.setattr("headroom.tokenizers.get_tokenizer", lambda model: ExactTokenizer())
    frame = {
        "type": "response.create",
        "response": {
            "model": "gpt-5",
            "instructions": "Follow project rules.",
            "input": "Fix failing test.",
        },
    }

    assert _estimate_openai_responses_output_shaper_input_tokens(frame, model="gpt-5") == 123
    assert seen_messages


def test_codex_ws_output_shaper_stratum_uses_estimated_input_tokens():
    frame = {
        "type": "response.create",
        "response": {
            "model": "gpt-5",
            "instructions": "Follow project rules.",
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Fix the failing proxy test."}],
                }
            ],
        },
    }

    input_tokens = _estimate_openai_responses_output_shaper_input_tokens(
        frame,
        model="gpt-5",
    )

    assert input_tokens > 0


def test_codex_ws_response_completed_records_shaped_response_in_stats(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    import headroom.proxy.output_savings as output_savings
    from headroom.proxy.output_savings import SavingsRecorder, stratum_label
    from headroom.proxy.server import ProxyConfig, create_app

    recorder = SavingsRecorder(tmp_path / "output_savings.json", flush_every=999)
    monkeypatch.setattr(output_savings, "get_recorder", lambda: recorder)
    monkeypatch.setenv("HEADROOM_OUTPUT_SHAPER", "1")
    monkeypatch.setenv("HEADROOM_VERBOSITY_LEVEL", "2")
    monkeypatch.setenv("HEADROOM_OUTPUT_HOLDOUT", "0")

    frame = {
        "type": "response.create",
        "response": {
            "model": "gpt-5",
            "instructions": "Follow project rules.",
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Fix the failing proxy test."}],
                }
            ],
        },
    }
    transforms: list[str] = []
    _apply_openai_responses_output_shaper(
        frame,
        model="gpt-5",
        input_tokens=_estimate_openai_responses_output_shaper_input_tokens(
            frame,
            model="gpt-5",
        ),
        transforms_applied=transforms,
        request_id="ws-req-1",
        endpoint="responses_ws",
        session_key="ws-session-1",
    )
    completed_event = {
        "type": "response.completed",
        "response": {
            "usage": {
                "input_tokens": 64,
                "output_tokens": 10,
                "input_tokens_details": {"cached_tokens": 0},
            }
        },
    }
    input_tokens, output_tokens, cache_read, cache_write, uncached = _extract_responses_usage(
        completed_event
    )
    handler = _DummyOpenAIHandler()

    anyio.run(
        handler._record_request_outcome,
        RequestOutcome(
            request_id="ws-req-1",
            provider="openai",
            model="gpt-5",
            original_tokens=input_tokens,
            optimized_tokens=input_tokens,
            output_tokens=output_tokens,
            tokens_saved=0,
            attempted_input_tokens=input_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            uncached_input_tokens=uncached,
            total_latency_ms=1.0,
            transforms_applied=tuple(transforms),
            tags={"client": "codex"},
            client="codex",
        ),
    )

    assert sum(acc.n for acc in recorder._ledger.treatment.values()) == 1
    treatment_key = next(iter(recorder._ledger.treatment))
    assert recorder.record_from_labels([stratum_label("control", treatment_key)], 20)

    app = create_app(
        ProxyConfig(
            optimize=False,
            cache_enabled=False,
            rate_limit_enabled=False,
            cost_tracking_enabled=False,
            log_requests=False,
            ccr_inject_tool=False,
            ccr_handle_responses=False,
            ccr_context_tracking=False,
        )
    )
    with TestClient(app) as client:
        payload = client.get("/stats").json()

    assert payload["tokens"]["output_reduction"]["requests"] == 1
    assert "output_shaper:verbosity:L2" in transforms


def test_openai_responses_output_shaper_records_output_savings(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")

    from fastapi.testclient import TestClient

    import headroom.proxy.output_savings as output_savings
    from headroom.proxy.output_savings import SavingsRecorder, stratum_label
    from headroom.proxy.server import ProxyConfig, create_app

    recorder = SavingsRecorder(tmp_path / "output_savings.json", flush_every=999)
    monkeypatch.setattr(output_savings, "get_recorder", lambda: recorder)
    monkeypatch.setenv("HEADROOM_OUTPUT_SHAPER", "1")
    monkeypatch.setenv("HEADROOM_VERBOSITY_LEVEL", "2")
    monkeypatch.setenv("HEADROOM_OUTPUT_HOLDOUT", "0")

    handler = _DummyOpenAIHandler()
    request = _build_request(
        {
            "model": "gpt-5",
            "instructions": "Follow project rules.",
            "input": "Fix failing test.",
        },
        {"Authorization": "Bearer test"},
    )

    response = anyio.run(handler.handle_openai_responses, request)

    assert response.status_code == 200
    assert sum(acc.n for acc in recorder._ledger.treatment.values()) == 1
    treatment_key = next(iter(recorder._ledger.treatment))
    assert recorder.record_from_labels([stratum_label("control", treatment_key)], 20)

    estimate = recorder.estimate()
    assert estimate.n_requests == 1
    assert estimate.baseline_tokens > 0

    app = create_app(
        ProxyConfig(
            optimize=False,
            cache_enabled=False,
            rate_limit_enabled=False,
            cost_tracking_enabled=False,
            log_requests=False,
            ccr_inject_tool=False,
            ccr_handle_responses=False,
            ccr_context_tracking=False,
        )
    )
    with TestClient(app) as client:
        payload = client.get("/stats").json()

    assert payload["tokens"]["output_reduction"]["requests"] == 1


def test_handle_openai_responses_ws_closes_unconfigured_origin(monkeypatch):
    handler = _DummyOpenAIHandler()
    websocket = _DummyWebSocket({"origin": "https://remote.example"})

    monkeypatch.delenv("HEADROOM_WS_ORIGINS", raising=False)
    monkeypatch.delenv("HEADROOM_CORS_ORIGINS", raising=False)

    with patch.dict(sys.modules, {"websockets": MagicMock()}):
        with patch(
            "headroom.proxy.handlers.openai._resolve_codex_routing_headers",
            side_effect=AssertionError("routing should not run"),
        ):
            anyio.run(handler.handle_openai_responses_ws, websocket)

    assert websocket.closed is True
    assert websocket.close_code == 1008
    assert websocket.close_reason == "origin not allowed"
    assert websocket.accepted_subprotocol is None
