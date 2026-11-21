"""Regression tests for Codex provider config cleanup."""

from __future__ import annotations

import importlib
import json
import sys
import types

import click
import pytest
import tomllib


def _load_init_module(monkeypatch):
    monkeypatch.delitem(sys.modules, "headroom.cli.init", raising=False)
    monkeypatch.delitem(sys.modules, "headroom.cli.main", raising=False)

    fake_main_module = types.ModuleType("headroom.cli.main")

    @click.group()
    def fake_main() -> None:
        pass

    fake_main_module.main = fake_main
    monkeypatch.setitem(sys.modules, "headroom.cli.main", fake_main_module)

    importlib.invalidate_caches()
    init_cli = importlib.import_module("headroom.cli.init")
    monkeypatch.delitem(sys.modules, "headroom.cli.init", raising=False)
    return init_cli


def test_ensure_codex_provider_removes_duplicate_headroom_provider_blocks(
    monkeypatch,
    tmp_path,
) -> None:
    init_cli = _load_init_module(monkeypatch)
    path = tmp_path / ".codex" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        """# --- Headroom init provider ---

# --- Headroom init provider ---
model_provider = "headroom"
openai_base_url = "http://headroom.example.test/p/fizzy/v1"

[model_providers.headroom]
name = "Headroom init proxy"
base_url = "http://headroom.example.test/p/fizzy/v1"
supports_websockets = true
requires_openai_auth = true
# --- end Headroom init provider ---

[model_providers.headroom]
name = "Headroom init proxy"
base_url = "http://headroom.example.test/p/headroom/v1"
supports_websockets = true
requires_openai_auth = true

[projects."/tmp/example"]
trust_level = "trusted"
""",
        encoding="utf-8",
    )

    init_cli._ensure_codex_provider(path, "http://headroom.example.test/p/headroom/v1")

    content = path.read_text(encoding="utf-8")
    parsed = tomllib.loads(content)
    assert content.count("[model_providers.headroom]") == 1
    assert parsed["model_provider"] == "headroom"
    assert parsed["experimental_realtime_webrtc_call_base_url"] == (
        "http://headroom.example.test/p/headroom/v1"
    )
    assert parsed["experimental_realtime_ws_base_url"] == (
        "http://headroom.example.test/p/headroom/v1"
    )
    assert parsed["model_providers"]["headroom"]["base_url"] == (
        "http://headroom.example.test/p/headroom/v1"
    )
    assert parsed["projects"]["/tmp/example"]["trust_level"] == "trusted"


@pytest.mark.parametrize("notes", ["", 'notes = """\nname = "Headroom init proxy"\n"""\n'])
def test_duplicate_user_provider_is_not_removed_by_managed_cleanup(
    monkeypatch, tmp_path, notes
) -> None:
    init_cli = _load_init_module(monkeypatch)
    path = tmp_path / ".codex" / "config.toml"
    path.parent.mkdir(parents=True)
    original = (
        f"{init_cli._CODEX_PROVIDER_MARKER_START}\n"
        'model_provider = "headroom"\n'
        '[model_providers.headroom]\nname = "Headroom init proxy"\n'
        'base_url = "http://127.0.0.1:9000/v1"\n'
        f"{init_cli._CODEX_PROVIDER_MARKER_END}\n\n"
        '[model_providers.headroom]\nname = "Private gateway"\n'
        'base_url = "https://gateway.example.test/v1"\n'
        "request_timeout_ms = 300000\n" + notes
    )
    path.write_text(original, encoding="utf-8")

    with pytest.raises(tomllib.TOMLDecodeError):
        init_cli._ensure_codex_provider(path, 8787)

    assert path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("indent", ["  ", "\t"])
@pytest.mark.parametrize(
    "foreign_table",
    [
        '[profiles.work]\nmodel = "gpt-5"\n',
        '[mcp_servers.user_tool]\ncommand = "tool"\n[mcp_servers.user_tool.env]\nKEEP = "yes"\n',
    ],
)
def test_duplicate_cleanup_preserves_indented_foreign_tables_and_provider_snapshot(
    monkeypatch, tmp_path, indent, foreign_table
) -> None:
    init_cli = _load_init_module(monkeypatch)
    path = tmp_path / ".codex" / "config.toml"
    path.parent.mkdir(parents=True)
    monkeypatch.setenv("CODEX_HOME", str(path.parent))
    snapshot = (
        '[model_providers.headroom]\nname = "Private gateway"\n'
        'base_url = "https://gateway.example.test/v1"\nrequest_timeout_ms = 300000\n'
    )
    foreign_content = "".join(indent + line for line in foreign_table.splitlines(keepends=True))
    path.write_text(
        f"{init_cli._CODEX_PROVIDER_MARKER_START}\n"
        'model_provider = "headroom"\n'
        '[model_providers.headroom]\nname = "OpenAI"\n'
        'base_url = "http://127.0.0.1:8787/v1"\nrequest_timeout_ms = 300000\n'
        f"{init_cli._CODEX_PROVIDER_SNAPSHOT_PREFIX}{json.dumps(snapshot)}\n"
        f"{init_cli._CODEX_PROVIDER_MARKER_END}\n\n"
        '[model_providers.headroom]\nname = "Headroom init proxy"\n'
        'base_url = "http://127.0.0.1:9000/v1"\n\n' + foreign_content,
        encoding="utf-8",
    )

    init_cli._ensure_codex_provider(path, 8787)

    content = path.read_text(encoding="utf-8")
    parsed = tomllib.loads(content)
    assert foreign_content in content
    foreign = tomllib.loads(foreign_content)
    for key, value in foreign.items():
        assert parsed[key] == value
    assert parsed["model_providers"]["headroom"]["request_timeout_ms"] == 300000
    assert init_cli._codex_init_provider_snapshot(content) == snapshot
    restored = tomllib.loads(init_cli._strip_codex_init_block(content))
    assert (
        restored["model_providers"]["headroom"]
        == tomllib.loads(snapshot)["model_providers"]["headroom"]
    )
    for key, value in foreign.items():
        assert restored[key] == value


@pytest.mark.parametrize("server_name", ["headroom", "serena"])
def test_duplicate_cleanup_preserves_following_mcp_marker_ownership(
    monkeypatch, tmp_path, server_name
) -> None:
    from headroom.mcp_registry import CodexRegistrar

    init_cli = _load_init_module(monkeypatch)
    path = tmp_path / ".codex" / "config.toml"
    path.parent.mkdir(parents=True)
    monkeypatch.setenv("CODEX_HOME", str(path.parent))
    suffix = "" if server_name == "headroom" else f": {server_name}"
    mcp_span = (
        f"# --- Headroom MCP server{suffix} ---\n"
        f'[mcp_servers.{server_name}]\ncommand = "tool"\n'
        f"# --- end Headroom MCP server{suffix} ---\n"
    )
    path.write_text(
        f"{init_cli._CODEX_PROVIDER_MARKER_START}\n"
        'model_provider = "headroom"\n'
        '[model_providers.headroom]\nname = "OpenAI"\n'
        'base_url = "http://127.0.0.1:8787/v1"\n'
        f"{init_cli._CODEX_PROVIDER_MARKER_END}\n\n"
        '[model_providers.headroom]\nname = "Headroom init proxy"\n'
        'base_url = "http://127.0.0.1:9000/v1"\n\n' + mcp_span,
        encoding="utf-8",
    )

    init_cli._ensure_codex_provider(path, 8787)

    assert mcp_span in path.read_text(encoding="utf-8")
    assert CodexRegistrar(home_dir=tmp_path).unregister_server(server_name) is True
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert parsed["model_provider"] == "headroom"
    assert parsed["model_providers"]["headroom"]["base_url"] == "http://127.0.0.1:8787/v1"
    assert server_name not in parsed.get("mcp_servers", {})
