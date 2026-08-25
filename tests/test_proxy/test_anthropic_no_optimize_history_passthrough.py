"""Regression coverage for Anthropic cached-prefix replay eligibility."""

from __future__ import annotations

import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
from fastapi.testclient import TestClient

from headroom.proxy.server import ProxyConfig, create_app

MODEL = "claude-sonnet-4-6"
MARKER = "large-tool-result-marker " * 80


def _config(**overrides) -> ProxyConfig:
    values = {
        "optimize": False,
        "cache_enabled": False,
        "rate_limit_enabled": False,
        "cost_tracking_enabled": False,
        "log_requests": False,
        "prefix_freeze_enabled": True,
    }
    values.update(overrides)
    return ProxyConfig(**values)


def _response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "ok"}],
            "model": MODEL,
            "usage": {"input_tokens": 10, "output_tokens": 2},
        },
    )


def _capture_proxy(client: TestClient) -> tuple[list[dict], AsyncMock]:
    captured: list[dict] = []

    async def capture(method, url, headers, body, stream=False, **kwargs):  # noqa: ANN001
        captured.append(copy.deepcopy(body))
        return _response()

    retry = AsyncMock(side_effect=capture)
    client.app.state.proxy._retry_request = retry
    return captured, retry


def _compact_bytes(messages: list[dict]) -> int:
    return len(json.dumps(messages, separators=(",", ":"), ensure_ascii=False).encode())


def _pipeline_result(messages: list[dict]) -> SimpleNamespace:
    return SimpleNamespace(
        messages=messages,
        transforms_applied=["test_stub"],
        timing={},
        tokens_before=1000,
        tokens_after=500,
        waste_signals=None,
    )


def test_no_optimize_second_turn_forwards_client_history_verbatim():
    """A bypass turn owns its Claude-shaped body after an optimized prior turn."""
    app = create_app(_config(optimize=True))
    tool_result = {
        "type": "tool_result",
        "tool_use_id": "toolu_01",
        "content": MARKER,
        "cache_control": {"type": "ephemeral"},
    }
    first = [{"role": "user", "content": [tool_result]}]
    compressed = copy.deepcopy(first)
    compressed[0]["content"][0]["content"] = "compressed-tool-result"
    app.state.proxy.anthropic_pipeline.apply = Mock(return_value=_pipeline_result(compressed))
    with TestClient(app) as client:
        captured, _ = _capture_proxy(client)
        response = client.post(
            "/v1/messages",
            json={"model": MODEL, "max_tokens": 16, "messages": first},
        )
        assert response.status_code == 200, response.text

        assistant = {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}
        current = [
            {
                "role": "user",
                "content": [{k: v for k, v in tool_result.items() if k != "cache_control"}],
            },
            assistant,
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_02",
                        "content": "next tool result",
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            },
        ]
        response = client.post(
            "/v1/messages",
            headers={"x-headroom-bypass": "true"},
            json={"model": MODEL, "max_tokens": 16, "messages": current},
        )

    assert response.status_code == 200, response.text
    outbound = captured[-1]["messages"]
    assert outbound[0]["content"][0]["content"] == MARKER
    assert "compressed-tool-result" not in json.dumps(outbound)
    assert sum(MARKER in json.dumps(message) for message in outbound) == 1
    assert _compact_bytes(outbound) <= _compact_bytes(current)


def test_optimize_off_real_exchange_reports_noninflation():
    app = create_app(_config(optimize=False))
    first = [
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_01",
                    "content": MARKER,
                }
            ],
        }
    ]
    current = first + [
        {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_02",
                    "content": "next tool result",
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        },
    ]
    with TestClient(app) as client:
        captured, _ = _capture_proxy(client)
        assert (
            client.post(
                "/v1/messages",
                json={"model": MODEL, "max_tokens": 16, "messages": first},
            ).status_code
            == 200
        )
        response = client.post(
            "/v1/messages",
            json={"model": MODEL, "max_tokens": 16, "messages": current},
        )

    assert response.status_code == 200, response.text
    outbound = captured[-1]["messages"]
    assert len(outbound) == 3
    assert sum(MARKER in json.dumps(message) for message in outbound) == 1
    assert _compact_bytes(outbound) == _compact_bytes(current) == 2293
    print(
        "optimize_off turn2_message_count=3 marker_count=1 "
        "outbound_compact_utf8_bytes=2293 client_compact_utf8_bytes=2293"
    )


def test_bypass_header_does_not_invoke_cached_prefix_replay(monkeypatch):
    app = create_app(_config(optimize=True))
    replay = monkeypatch.setattr

    def fail_if_called(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("cached-prefix replay must be bypassed")

    replay("headroom.cache.prefix_tracker.overlay_cached_prefix", fail_if_called)
    with TestClient(app) as client:
        captured, _ = _capture_proxy(client)
        messages = [{"role": "user", "content": "bypass"}]
        response = client.post(
            "/v1/messages",
            headers={"x-headroom-bypass": "true"},
            json={"model": MODEL, "max_tokens": 16, "messages": messages},
        )

    assert response.status_code == 200, response.text
    assert captured[-1]["messages"] == messages


def test_backpressure_does_not_invoke_cached_prefix_replay(monkeypatch):
    app = create_app(
        _config(
            optimize=True,
            anthropic_pre_upstream_concurrency=1,
            anthropic_pre_upstream_acquire_timeout_seconds=0.001,
        )
    )

    def fail_if_called(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("cached-prefix replay must be skipped under backpressure")

    monkeypatch.setattr("headroom.cache.prefix_tracker.overlay_cached_prefix", fail_if_called)
    debug = Mock()
    monkeypatch.setattr("headroom.proxy.handlers.anthropic.logger.debug", debug)
    proxy = app.state.proxy

    class _SaturatedSemaphore:
        async def acquire(self):
            await asyncio.sleep(1)

        def release(self):
            pass

    proxy.anthropic_pre_upstream_sem = _SaturatedSemaphore()
    try:
        with TestClient(app) as client:
            captured, _ = _capture_proxy(client)
            messages = [{"role": "user", "content": "backpressure"}]
            response = client.post(
                "/v1/messages",
                json={"model": MODEL, "max_tokens": 16, "messages": messages},
            )
    finally:
        proxy.anthropic_pre_upstream_sem.release()

    assert response.status_code == 200, response.text
    assert captured[-1]["messages"] == messages
    assert any(
        call.args and call.args[-1] == "pre_upstream_backpressure" for call in debug.call_args_list
    )


def test_optimize_on_aligned_history_preserves_replay():
    app = create_app(_config(optimize=True))
    first = [{"role": "user", "content": "original prefix"}]
    compressed = [{"role": "user", "content": "comp"}]
    assistant = {
        "role": "assistant",
        "content": [{"type": "text", "text": "ok", "cache_control": {"type": "ephemeral"}}],
    }
    current = first + [assistant, {"role": "user", "content": "new suffix"}]
    optimized = compressed + [assistant, {"role": "user", "content": "new suffix"}]
    app.state.proxy.anthropic_pipeline.apply = Mock(
        side_effect=[_pipeline_result(compressed), _pipeline_result(optimized)]
    )
    with TestClient(app) as client:
        captured, _ = _capture_proxy(client)
        response = client.post(
            "/v1/messages",
            json={"model": MODEL, "max_tokens": 16, "messages": first},
        )
        assert response.status_code == 200, response.text
        response = client.post(
            "/v1/messages",
            json={"model": MODEL, "max_tokens": 16, "messages": current},
        )

    assert response.status_code == 200, response.text
    outbound = captured[-1]["messages"]
    assert outbound[0] == compressed[0]
    assert outbound[-1] == optimized[-1]
    print(
        f"optimize_on turn2_message_count={len(outbound)} client_message_count={len(current)} "
        f"marker_count={sum(MARKER in json.dumps(message) for message in outbound)} "
        f"outbound_compact_utf8_bytes={_compact_bytes(outbound)} "
        f"client_compact_utf8_bytes={_compact_bytes(current)}"
    )
