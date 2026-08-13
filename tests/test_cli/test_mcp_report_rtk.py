from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import click
from click.testing import CliRunner


def _load_mcp_module(monkeypatch):
    monkeypatch.delitem(sys.modules, "headroom.cli.mcp", raising=False)
    monkeypatch.delitem(sys.modules, "headroom.cli.main", raising=False)
    fake_main_module = types.ModuleType("headroom.cli.main")

    @click.group()
    def fake_main() -> None:
        pass

    fake_main_module.main = fake_main
    monkeypatch.setitem(sys.modules, "headroom.cli.main", fake_main_module)
    importlib.invalidate_caches()
    mcp_cli = importlib.import_module("headroom.cli.mcp")
    monkeypatch.delitem(sys.modules, "headroom.cli.mcp", raising=False)
    return mcp_cli, fake_main


def test_report_rtk_resolves_executable_from_path(monkeypatch) -> None:
    mcp_cli, fake_main = _load_mcp_module(monkeypatch)
    monkeypatch.setattr(mcp_cli, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(mcp_cli.shutil, "which", lambda name: "/opt/rtk/bin/rtk")

    captured: dict[str, Path] = {}

    def capture_command(path: Path, scope: str) -> list[str]:
        captured["path"] = path
        raise RuntimeError("stop after resolution")

    monkeypatch.setattr(mcp_cli, "_rtk_gain_command", capture_command)

    result = CliRunner().invoke(fake_main, ["mcp", "report-rtk"])

    assert isinstance(result.exception, RuntimeError)
    assert captured["path"] == Path("/opt/rtk/bin/rtk")


def test_report_rtk_errors_when_executable_is_missing(monkeypatch) -> None:
    mcp_cli, fake_main = _load_mcp_module(monkeypatch)
    monkeypatch.setattr(mcp_cli.shutil, "which", lambda name: None)

    result = CliRunner().invoke(fake_main, ["mcp", "report-rtk"])

    assert result.exit_code == 1
    assert "rtk is not installed or not on PATH" in result.output
