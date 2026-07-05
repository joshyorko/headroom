"""Regression tests for Codex provider config cleanup."""

from __future__ import annotations

import importlib
import sys
import types

import click
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
    assert parsed["model_providers"]["headroom"]["base_url"] == (
        "http://headroom.example.test/p/headroom/v1"
    )
    assert parsed["projects"]["/tmp/example"]["trust_level"] == "trusted"
