import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from headroom.cli.main import main
from headroom.proxy import helpers


def _reset_context_tool_state() -> None:
    with helpers._context_tool_stats_cache_lock:
        helpers._context_tool_reported_snapshot.update(
            {
                "tool": None,
                "value": None,
                "reported_at": 0.0,
                "source": None,
            }
        )
        helpers._context_tool_reported_project_snapshots.clear()
        helpers._context_tool_stats_cache.update(
            {
                "expires_at": 0.0,
                "has_value": False,
                "tool": None,
                "value": None,
            }
        )
        helpers._context_tool_session_baseline.update(
            {
                "initialized": True,
                "tool": "rtk",
                "source": None,
                "scope": None,
                "total_commands": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "tokens_saved": 0,
                "total_time_ms": 0,
                "captured_at": 0.0,
            }
        )


def test_context_tool_report_feeds_stats_payload() -> None:
    _reset_context_tool_state()

    accepted = helpers.ingest_context_tool_stats(
        {
            "tool": "rtk",
            "scope": "project",
            "summary": {
                "total_commands": 3,
                "total_input": 100,
                "total_output": 25,
                "total_saved": 75,
                "avg_savings_pct": 75.0,
                "total_time_ms": 12,
            },
        },
        source="test",
    )
    stats = helpers._get_context_tool_stats()

    assert accepted["tokens_saved"] == 75
    assert stats is not None
    assert stats["reported"] is True
    assert stats["scope"] == "project"
    assert stats["tokens_saved"] == 0
    assert stats["session_delta_available"] is False
    assert stats["session_delta_unavailable_reason"] == "baseline_unavailable"
    assert stats["lifetime"]["tokens_saved"] == 75
    assert stats["session"]["tokens_saved"] == 0
    assert stats["session"]["commands"] == 0

    helpers.ingest_context_tool_stats(
        {
            "tool": "rtk",
            "scope": "project",
            "summary": {
                "total_commands": 5,
                "total_input": 140,
                "total_output": 40,
                "total_saved": 100,
                "avg_savings_pct": 71.42,
                "total_time_ms": 20,
            },
        },
        source="test",
    )
    second = helpers._get_context_tool_stats()

    assert second is not None
    assert second["tokens_saved"] == 25
    assert second["session_delta_available"] is True
    assert second["session"]["commands"] == 2
    assert second["session"]["tokens_saved"] == 25
    assert second["lifetime"]["tokens_saved"] == 100


def test_context_tool_report_rejects_unsupported_tool() -> None:
    _reset_context_tool_state()

    try:
        helpers.ingest_context_tool_stats({"tool": "bogus", "summary": {}})
    except ValueError as exc:
        assert "unsupported context tool" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_context_tool_report_endpoint_updates_stats_payload() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from headroom.proxy.server import ProxyConfig, create_app

    app = create_app(
        ProxyConfig(
            cache_enabled=False,
            rate_limit_enabled=False,
            cost_tracking_enabled=False,
        )
    )
    with TestClient(app) as client:
        _reset_context_tool_state()
        response = client.post(
            "/stats/context-tool",
            json={
                "tool": "rtk",
                "scope": "project",
                "summary": {
                    "total_commands": 2,
                    "total_input": 50,
                    "total_output": 10,
                    "total_saved": 40,
                },
            },
        )
        assert response.status_code == 200
        assert response.json()["context_tool"]["tokens_saved"] == 40

        stats = client.get("/stats?cached=0").json()
        assert stats["tokens"]["cli_filtering_saved"] == 0
        assert stats["context_tool"]["stats"]["reported"] is True
        assert stats["context_tool"]["stats"]["session_delta_available"] is False
        assert stats["context_tool"]["stats"]["lifetime"]["tokens_saved"] == 40
        assert stats["savings"]["by_layer"]["cli_filtering"]["lifetime"]["tokens_saved"] == 40


def test_context_tool_report_adds_project_row_from_cwd() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from headroom.proxy.server import ProxyConfig, create_app

    app = create_app(ProxyConfig(rate_limit_enabled=False))
    _reset_context_tool_state()
    client = TestClient(app)

    response = client.post(
        "/stats/context-tool",
        json={
            "tool": "rtk",
            "scope": "project",
            "cwd": "/work/room-of-requirement",
            "summary": {
                "total_commands": 105,
                "total_input": 123868,
                "total_output": 28525,
                "total_saved": 95364,
            },
        },
    )

    assert response.status_code == 200
    stats = client.get("/stats?cached=0").json()
    project = stats["savings"]["per_project"]["room-of-requirement"]
    assert project["tokens_saved"] == 95364
    assert project["rtk_tokens_saved"] == 95364
    assert project["rtk_commands"] == 105
    assert project["savings_percent"] == 76.99


def test_context_tool_report_accumulates_multiple_project_rows() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from headroom.proxy.server import ProxyConfig, create_app

    app = create_app(ProxyConfig(rate_limit_enabled=False))
    _reset_context_tool_state()
    client = TestClient(app)

    for cwd, saved, commands, input_tokens in (
        ("/work/headroom", 100, 4, 200),
        ("/work/codex-desktop-linux", 250, 9, 500),
    ):
        response = client.post(
            "/stats/context-tool",
            json={
                "tool": "rtk",
                "scope": "project",
                "cwd": cwd,
                "summary": {
                    "total_commands": commands,
                    "total_input": input_tokens,
                    "total_output": input_tokens - saved,
                    "total_saved": saved,
                },
            },
        )
        assert response.status_code == 200

    stats = client.get("/stats?cached=0").json()
    per_project = stats["savings"]["per_project"]
    assert per_project["headroom"]["rtk_tokens_saved"] == 100
    assert per_project["headroom"]["rtk_commands"] == 4
    assert per_project["codex-desktop-linux"]["rtk_tokens_saved"] == 250
    assert per_project["codex-desktop-linux"]["rtk_commands"] == 9
    assert stats["context_tool"]["stats"]["cwd"] == "/work/codex-desktop-linux"


def test_mcp_report_rtk_posts_project_stats(monkeypatch) -> None:
    import headroom.cli.mcp as mcp_mod
    import headroom.rtk as rtk_mod

    monkeypatch.setattr(rtk_mod, "get_rtk_path", lambda: Path("/usr/bin/rtk"))

    def fake_run(command, **kwargs):
        assert command == ["/usr/bin/rtk", "gain", "--project", "--format", "json"]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "summary": {
                        "total_commands": 5,
                        "total_input": 200,
                        "total_output": 80,
                        "total_saved": 120,
                        "avg_savings_pct": 60.0,
                    }
                }
            ),
            stderr="",
        )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "ok": True,
                    "context_tool": {
                        "tokens_saved": 120,
                        "total_commands": 5,
                    },
                }
            ).encode("utf-8")

    posted = {}

    def fake_urlopen(request, timeout):
        posted["url"] = request.full_url
        posted["body"] = json.loads(request.data.decode("utf-8"))
        posted["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(mcp_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mcp_mod.urllib.request, "urlopen", fake_urlopen)

    result = CliRunner().invoke(
        main,
        ["mcp", "report-rtk", "--proxy-url", "http://headroom.example.test"],
    )

    assert result.exit_code == 0, result.output
    assert posted["url"] == "http://headroom.example.test/stats/context-tool"
    assert posted["body"]["tool"] == "rtk"
    assert posted["body"]["scope"] == "project"
    assert posted["body"]["summary"]["total_saved"] == 120
    assert "120 tokens saved across 5 commands" in result.output
