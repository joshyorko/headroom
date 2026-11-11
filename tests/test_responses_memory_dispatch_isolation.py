"""Actual MemoryHandler/resolver dispatch with SQLite storage, without embedders.

The legacy class is a test adapter over the canonical unscoped implementation;
no production or sampled historical handler with that old signature was found.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from headroom.memory.adapters.sqlite import SQLiteMemoryStore
from headroom.memory.models import Memory
from headroom.memory.ports import MemoryFilter
from headroom.memory.storage_router import MemoryStorageMode, RequestContext
from headroom.proxy.handlers.openai import OpenAIHandlerMixin
from headroom.proxy.memory_handler import MemoryConfig, MemoryHandler


class _SQLiteToolBackend:
    """Only bridge the backend protocol; persistence/filtering use the real store."""

    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.store = SQLiteMemoryStore(path)

    async def save_memory(self, *, content, user_id, importance=0.5, metadata=None, **kwargs):
        memory = Memory(
            content=content, user_id=user_id, importance=importance, metadata=metadata or {}
        )
        await self.store.save(memory)
        return memory

    async def search_memories(self, *, user_id, **kwargs):
        memories = await self.store.query(MemoryFilter(user_id=user_id))
        return [SimpleNamespace(memory=m, score=0.5, related_entities=[]) for m in memories]


class _LegacySignatureMemoryHandler(MemoryHandler):
    async def _execute_memory_tool(self, name, args, user_id, provider="anthropic"):
        return await super()._execute_memory_tool(name, args, user_id, provider)


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True], ids=["canonical", "legacy-adapter"])
@pytest.mark.parametrize(
    "backend_kind, mode",
    [
        ("local", MemoryStorageMode.GLOBAL),
        ("local", MemoryStorageMode.USER),
        ("local", MemoryStorageMode.PROJECT),
        ("qdrant-neo4j", MemoryStorageMode.PROJECT),
    ],
)
async def test_dispatch_keeps_actual_handler_resolver_and_sqlite_user_partitions(
    tmp_path, monkeypatch, legacy, backend_kind, mode
):
    handler_class = _LegacySignatureMemoryHandler if legacy else MemoryHandler
    handler = handler_class(
        MemoryConfig(
            enabled=True,
            backend=backend_kind,
            storage_mode=mode,
            db_path=str(tmp_path / "global.db"),
            storage_root=str(tmp_path / "projects"),
            inject_context=False,
        )
    )
    global_backend = _SQLiteToolBackend(tmp_path / "global.db")
    handler._backend = global_backend
    handler._initialized = True
    backends = {tmp_path / "global.db": global_backend}

    def backend_for_path(path):
        if path not in backends:
            backends[path] = _SQLiteToolBackend(path)
        return backends[path]

    monkeypatch.setattr(handler._router, "_get_or_create_backend", backend_for_path)
    dispatch = OpenAIHandlerMixin._execute_responses_memory_tool
    proxy = SimpleNamespace(memory_handler=handler)
    targets = {}
    contexts = []
    for user, project in [("alice", "alpha"), ("alice", "beta"), ("bob", "alpha")]:
        context = RequestContext(
            headers={"x-headroom-project-id": project}, system_prompt="", base_user_id=user
        )
        contexts.append((user, project, context))
        backend, scope, effective_user = handler._resolve_for_request(user, context)
        assert scope is not None
        content = f"private note for {user}/{project}"
        response = json.loads(
            await dispatch(proxy, "memory_save", {"content": content}, user, context)
        )
        if legacy and backend is not global_backend:
            assert response == {"status": "skipped", "reason": "legacy_request_scope_unsupported"}
        else:
            assert response["status"] == "saved"
            targets.setdefault((backend, effective_user), []).append(content)
        assert handler._backend is global_backend

    for user, _project, context in contexts:
        backend, _, effective_user = handler._resolve_for_request(user, context)
        response = json.loads(
            await dispatch(proxy, "memory_search", {"query": "private note"}, user, context)
        )
        if legacy and backend is not global_backend:
            assert response["reason"] == "legacy_request_scope_unsupported"
            assert await backend.store.query(MemoryFilter(user_id=user)) == []
        else:
            actual = sorted(m["content"] for m in response["memories"])
            assert actual == sorted(targets[(backend, effective_user)])
            persisted = await backend.store.query(MemoryFilter(user_id=effective_user))
            assert sorted(m.content for m in persisted) == actual
            if backend_kind == "qdrant-neo4j":
                assert effective_user.startswith(user + "::")
                assert await backend.store.query(MemoryFilter(user_id=user)) == []
    assert handler._backend is global_backend


@pytest.mark.asyncio
async def test_legacy_adapter_without_resolver_refuses_context_instead_of_using_default_backend():
    calls = []

    async def execute(name, args, user_id, provider):
        calls.append(user_id)
        return "unexpected"

    async def initialized():
        pass

    handler = SimpleNamespace(
        _execute_memory_tool=execute, _ensure_initialized=initialized, _backend=object()
    )
    context = RequestContext(
        headers={"x-headroom-project-id": "alpha"}, system_prompt="", base_user_id="alice"
    )
    response = await OpenAIHandlerMixin._execute_responses_memory_tool(
        SimpleNamespace(memory_handler=handler),
        "memory_search",
        {"query": "private"},
        "alice",
        context,
    )
    assert json.loads(response) == {
        "status": "skipped",
        "reason": "legacy_request_scope_unsupported",
    }
    assert calls == []


@pytest.mark.asyncio
async def test_actual_legacy_adapter_without_context_preserves_user_partition(tmp_path):
    handler = _LegacySignatureMemoryHandler(MemoryConfig(enabled=True))
    handler._backend = _SQLiteToolBackend(tmp_path / "legacy.db")
    handler._initialized = True
    proxy = SimpleNamespace(memory_handler=handler)
    dispatch = OpenAIHandlerMixin._execute_responses_memory_tool
    for user in ("alice", "bob"):
        result = json.loads(
            await dispatch(proxy, "memory_save", {"content": user + " private"}, user)
        )
        assert result["status"] == "saved"
    result = json.loads(await dispatch(proxy, "memory_search", {"query": "private"}, "alice"))
    assert [m["content"] for m in result["memories"]] == ["alice private"]
