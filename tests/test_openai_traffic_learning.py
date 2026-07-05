"""OpenAI/Codex traffic-learning integration tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from headroom.proxy.server import ProxyConfig, create_app


class _FakeTrafficLearner:
    def __init__(self) -> None:
        self._backend = None
        self.backend_set: Any | None = None
        self.tool_extract_messages: list[list[dict[str, Any]]] = []
        self.message_batches: list[list[dict[str, Any]]] = []
        self.message_user_ids: list[str | None] = []
        self.message_backends: list[Any | None] = []
        self.tool_results: list[dict[str, Any]] = []

    def set_backend(self, backend: Any) -> None:
        self._backend = backend
        self.backend_set = backend

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    def extract_tool_results_from_messages(
        self, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        self.tool_extract_messages.append(messages)
        return []

    async def on_tool_result(
        self,
        *,
        tool_name: str,
        tool_input: dict[str, Any],
        tool_output: str,
        is_error: bool,
        user_id: str | None = None,
        backend: Any | None = None,
    ) -> None:
        self.tool_results.append(
            {
                "tool_name": tool_name,
                "tool_input": tool_input,
                "tool_output": tool_output,
                "is_error": is_error,
                "user_id": user_id,
                "backend": backend,
            }
        )

    async def on_messages(
        self,
        messages: list[dict[str, Any]],
        agent_type: str = "unknown",
        user_id: str | None = None,
        backend: Any | None = None,
    ) -> None:
        self.message_batches.append(messages)
        self.message_user_ids.append(user_id)
        self.message_backends.append(backend)


class _FakeMemoryHandler:
    def __init__(self) -> None:
        self.config = SimpleNamespace(inject_context=False, inject_tools=False)
        self.initialized = True
        self.backend = object()
        self._backend = object()
        self.executed_request_context: Any | None = None

    async def _ensure_initialized(self) -> None:
        return None

    def has_memory_tool_calls(self, response: dict[str, Any], provider: str) -> bool:
        return any(
            isinstance(item, dict)
            and item.get("type") == "function_call"
            and item.get("name") == "memory_save"
            for item in response.get("output", [])
        )

    async def _execute_memory_tool(
        self,
        name: str,
        args: dict[str, Any],
        user_id: str,
        provider: str,
        *,
        request_context: Any | None = None,
    ) -> str:
        self.executed_request_context = request_context
        return '{"status":"saved","memory_id":"mem_1"}'


class _FakeScopedMemoryHandler:
    def __init__(self, backend: Any) -> None:
        self.config = SimpleNamespace(inject_context=False, inject_tools=False)
        self.initialized = True
        self.backend = backend

    def _resolve_for_request(
        self,
        base_user_id: str,
        request_context: Any,
    ) -> tuple[Any, Any, str]:
        return (
            self.backend,
            SimpleNamespace(display_name="headroom-test-project"),
            (f"{base_user_id}::{request_context.headers['x-headroom-project-id']}"),
        )

    def has_memory_tool_calls(self, response: dict[str, Any], provider: str) -> bool:
        return False


def test_openai_responses_feeds_traffic_learner() -> None:
    config = ProxyConfig(
        optimize=False,
        cache_enabled=False,
        rate_limit_enabled=False,
        cost_tracking_enabled=False,
        log_requests=False,
        ccr_inject_tool=False,
        ccr_handle_responses=False,
        ccr_context_tracking=False,
        image_optimize=False,
        memory_enabled=True,
        traffic_learning_enabled=True,
    )
    app = create_app(config)

    with TestClient(app) as client:
        proxy = client.app.state.proxy
        backend = object()
        proxy.memory_handler = SimpleNamespace(
            initialized=True,
            backend=backend,
            config=SimpleNamespace(inject_context=False, inject_tools=False),
            has_memory_tool_calls=lambda response, provider: False,
        )
        learner = _FakeTrafficLearner()
        proxy.traffic_learner = learner

        async def _fake_retry(
            method: str,
            url: str,
            headers: dict[str, str],
            body: dict[str, Any],
            stream: bool = False,
            **kwargs: Any,
        ) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "id": "resp_1",
                    "object": "response",
                    "model": "gpt-5.4",
                    "output": [],
                    "usage": {"input_tokens": 5, "output_tokens": 1},
                },
            )

        proxy._retry_request = _fake_retry

        response = client.post(
            "/v1/responses",
            headers={
                "authorization": "Bearer sk-test",
                "x-headroom-user-id": "u1",
            },
            json={
                "model": "gpt-5.4",
                "input": [
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": "No, use httpx not requests."}],
                    }
                ],
            },
        )

    assert response.status_code == 200
    assert learner.backend_set is backend
    assert learner.message_batches
    assert learner.tool_extract_messages


def test_openai_responses_feeds_request_scoped_user_to_traffic_learner() -> None:
    config = ProxyConfig(
        optimize=False,
        cache_enabled=False,
        rate_limit_enabled=False,
        cost_tracking_enabled=False,
        log_requests=False,
        ccr_inject_tool=False,
        ccr_handle_responses=False,
        ccr_context_tracking=False,
        image_optimize=False,
        memory_enabled=True,
        traffic_learning_enabled=True,
    )
    app = create_app(config)

    with TestClient(app) as client:
        proxy = client.app.state.proxy
        backend = object()
        proxy.memory_handler = _FakeScopedMemoryHandler(backend)
        learner = _FakeTrafficLearner()
        proxy.traffic_learner = learner

        async def _fake_retry(
            method: str,
            url: str,
            headers: dict[str, str],
            body: dict[str, Any],
            stream: bool = False,
            **kwargs: Any,
        ) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "id": "resp_1",
                    "object": "response",
                    "model": "gpt-5.4",
                    "output": [],
                    "usage": {"input_tokens": 5, "output_tokens": 1},
                },
            )

        proxy._retry_request = _fake_retry

        response = client.post(
            "/v1/responses",
            headers={
                "authorization": "Bearer sk-test",
                "x-headroom-user-id": "u1",
                "x-headroom-project-id": "proj-a",
            },
            json={
                "model": "gpt-5.4",
                "input": [
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": "No, use httpx."}],
                    }
                ],
            },
        )

    assert response.status_code == 200
    assert learner.message_user_ids == ["u1::proj-a"]
    assert learner.message_backends == [backend]


def test_openai_responses_memory_save_keeps_request_context() -> None:
    config = ProxyConfig(
        optimize=False,
        cache_enabled=False,
        rate_limit_enabled=False,
        cost_tracking_enabled=False,
        log_requests=False,
        ccr_inject_tool=False,
        ccr_handle_responses=False,
        ccr_context_tracking=False,
        image_optimize=False,
        memory_enabled=True,
    )
    app = create_app(config)

    with TestClient(app) as client:
        proxy = client.app.state.proxy
        memory_handler = _FakeMemoryHandler()
        proxy.memory_handler = memory_handler

        calls: list[dict[str, Any]] = []

        async def _fake_retry(
            method: str,
            url: str,
            headers: dict[str, str],
            body: dict[str, Any],
            stream: bool = False,
            **kwargs: Any,
        ) -> httpx.Response:
            calls.append(body)
            if len(calls) == 1:
                return httpx.Response(
                    200,
                    json={
                        "id": "resp_memory",
                        "object": "response",
                        "model": "gpt-5.4",
                        "output": [
                            {
                                "type": "function_call",
                                "name": "memory_save",
                                "call_id": "call_1",
                                "arguments": '{"content":"Josh prefers focused tests"}',
                            }
                        ],
                        "usage": {"input_tokens": 5, "output_tokens": 1},
                    },
                )
            return httpx.Response(
                200,
                json={
                    "id": "resp_final",
                    "object": "response",
                    "model": "gpt-5.4",
                    "output": [],
                    "usage": {"input_tokens": 6, "output_tokens": 2},
                },
            )

        proxy._retry_request = _fake_retry

        response = client.post(
            "/v1/responses",
            headers={
                "authorization": "Bearer sk-test",
                "x-headroom-user-id": "u1",
                "x-headroom-project-id": "headroom-test-project",
            },
            json={
                "model": "gpt-5.4",
                "input": "Save this preference.",
            },
        )

    assert response.status_code == 200
    assert memory_handler.executed_request_context is not None
    assert memory_handler.executed_request_context.base_user_id == "u1"
    assert (
        memory_handler.executed_request_context.headers["x-headroom-project-id"]
        == "headroom-test-project"
    )
