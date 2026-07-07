from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from headroom.dashboard import get_dashboard_html
from headroom.proxy import helpers as proxy_helpers


class _StatsStub:
    def __init__(self, calls: dict[str, int], key: str, payload: dict):
        self._calls = calls
        self._key = key
        self._payload = payload

    def get_stats(self) -> dict:
        self._calls[self._key] += 1
        return dict(self._payload)


class _ToinStub:
    def get_stats(self) -> dict:
        return {"patterns": 0}


@pytest.fixture(autouse=True)
def _reset_rtk_stats_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HEADROOM_CONTEXT_TOOL", raising=False)
    monkeypatch.delenv("HEADROOM_RTK_GAIN_SCOPE", raising=False)
    monkeypatch.setenv("HEADROOM_REQUIRE_RUST_CORE", "false")
    proxy_helpers._rtk_stats_cache.update(
        {"expires_at": 0.0, "has_value": False, "tool": None, "value": None}
    )
    proxy_helpers._context_tool_reported_snapshot.update(
        {"tool": None, "value": None, "reported_at": 0.0, "source": None}
    )
    proxy_helpers._context_tool_reported_project_snapshots.clear()
    proxy_helpers._rtk_session_baseline.update(
        {
            "initialized": False,
            "tool": None,
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


def test_get_rtk_stats_memoizes_subprocess_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HEADROOM_CONTEXT_TOOL", raising=False)
    now = {"value": 100.0}
    calls = {"run": 0}
    totals = [
        {
            "total_commands": 7,
            "total_input": 2000,
            "total_output": 766,
            "total_saved": 1234,
            "avg_savings_pct": 61.7,
            "total_time_ms": 700,
        },
        {
            "total_commands": 9,
            "total_input": 2600,
            "total_output": 1100,
            "total_saved": 1500,
            "avg_savings_pct": 57.69,
            "total_time_ms": 1000,
        },
    ]

    def _fake_run(args, **kwargs):
        calls["run"] += 1
        assert [str(args[0]).replace("\\", "/")] + args[1:] == [
            "/usr/bin/rtk",
            "gain",
            "--format",
            "json",
        ]
        summary = totals[min(calls["run"] - 1, len(totals) - 1)]
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"summary": summary}),
        )

    monkeypatch.setattr(proxy_helpers.time, "monotonic", lambda: now["value"])
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/rtk")
    monkeypatch.setattr(subprocess, "run", _fake_run)

    first = proxy_helpers._get_rtk_stats()
    second = proxy_helpers._get_rtk_stats()

    assert first == second
    assert first["tool"] == "rtk"
    assert first["label"] == "RTK"
    assert first["installed"] is True
    assert first["scope"] == "global"
    assert first["total_commands"] == 0
    assert first["input_tokens"] == 0
    assert first["output_tokens"] == 0
    assert first["tokens_saved"] == 0
    assert first["session_savings_pct"] is None
    assert first["avg_savings_pct"] == 61.7
    assert first["avg_savings_pct_scope"] == "lifetime"
    assert first["lifetime_total_commands"] == 7
    assert first["lifetime_input_tokens"] == 2000
    assert first["lifetime_output_tokens"] == 766
    assert first["lifetime_tokens_saved"] == 1234
    assert first["session_baseline_total_commands"] == 7
    assert first["session_baseline_input_tokens"] == 2000
    assert first["session_baseline_output_tokens"] == 766
    assert first["session_baseline_tokens_saved"] == 1234
    assert first["session"]["tokens_saved"] == 0
    assert first["lifetime"]["savings_pct"] == 61.7
    assert first["sample_ttl_seconds"] == proxy_helpers.CONTEXT_TOOL_STATS_CACHE_TTL_SECONDS
    assert calls["run"] == 1

    now["value"] += proxy_helpers.RTK_STATS_CACHE_TTL_SECONDS + 0.1
    third = proxy_helpers._get_rtk_stats()

    assert third["tool"] == "rtk"
    assert third["label"] == "RTK"
    assert third["installed"] is True
    assert third["total_commands"] == 2
    assert third["input_tokens"] == 600
    assert third["output_tokens"] == 334
    assert third["tokens_saved"] == 266
    assert third["session_savings_pct"] == pytest.approx(44.3333)
    assert third["session_avg_time_ms"] == 150.0
    assert third["lifetime_total_commands"] == 9
    assert third["lifetime_input_tokens"] == 2600
    assert third["lifetime_output_tokens"] == 1100
    assert third["lifetime_tokens_saved"] == 1500
    assert third["session_baseline_total_commands"] == 7
    assert third["session_baseline_input_tokens"] == 2000
    assert third["session_baseline_output_tokens"] == 766
    assert third["session_baseline_tokens_saved"] == 1234
    assert third["session"] == {
        "commands": 2,
        "input_tokens": 600,
        "output_tokens": 334,
        "tokens_saved": 266,
        "savings_pct": pytest.approx(44.3333),
        "total_time_ms": 300,
        "avg_time_ms": 150.0,
    }
    assert calls["run"] == 2


def test_get_rtk_stats_can_read_project_scoped_gain(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"run": 0}

    def _fake_run(args, **kwargs):
        calls["run"] += 1
        assert [str(args[0]).replace("\\", "/")] + args[1:] == [
            "/usr/bin/rtk",
            "gain",
            "--project",
            "--format",
            "json",
        ]
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "summary": {
                        "total_commands": 1,
                        "total_input": 100,
                        "total_output": 75,
                        "total_saved": 25,
                    }
                }
            ),
        )

    monkeypatch.setenv("HEADROOM_RTK_GAIN_SCOPE", "project")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/rtk")
    monkeypatch.setattr(subprocess, "run", _fake_run)

    payload = proxy_helpers._read_rtk_lifetime_stats()

    assert payload is not None
    assert payload["scope"] == "project"
    assert payload["total_commands"] == 1
    assert payload["tokens_saved"] == 25
    assert calls["run"] == 1


def test_get_rtk_stats_invalid_scope_defaults_to_global(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"run": 0}

    def _fake_run(args, **kwargs):
        calls["run"] += 1
        assert [str(args[0]).replace("\\", "/")] + args[1:] == [
            "/usr/bin/rtk",
            "gain",
            "--format",
            "json",
        ]
        return SimpleNamespace(returncode=0, stdout=json.dumps({"summary": {}}))

    mock_warning = MagicMock()
    monkeypatch.setenv("HEADROOM_RTK_GAIN_SCOPE", "workspace")
    monkeypatch.setattr(proxy_helpers.logger, "warning", mock_warning)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/rtk")
    monkeypatch.setattr(subprocess, "run", _fake_run)

    payload = proxy_helpers._read_rtk_lifetime_stats()

    assert payload is not None
    assert payload["scope"] == "global"
    assert calls["run"] == 1
    warning_calls = " ".join(str(call) for call in mock_warning.call_args_list)
    assert "event=rtk_gain_scope_invalid" in warning_calls


def test_get_context_tool_stats_reads_lean_ctx_gain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEADROOM_CONTEXT_TOOL", "lean-ctx")
    now = {"value": 100.0}
    calls = {"run": 0}
    totals = [
        {
            "total_commands": 3,
            "total_input_tokens": 1000,
            "total_output_tokens": 600,
            "tokens_saved": 400,
            "avg_savings_pct": 40.0,
        },
        {
            "total_commands": 5,
            "total_input_tokens": 1250,
            "total_output_tokens": 775,
            "tokens_saved": 475,
            "avg_savings_pct": 38.0,
        },
    ]

    def _fake_run(args, **kwargs):
        calls["run"] += 1
        assert [str(args[0]).replace("\\", "/")] + args[1:] == [
            "/usr/bin/lean-ctx",
            "gain",
            "--json",
        ]
        summary = totals[min(calls["run"] - 1, len(totals) - 1)]
        return SimpleNamespace(returncode=0, stdout=json.dumps({"summary": summary}))

    monkeypatch.setattr(proxy_helpers.time, "monotonic", lambda: now["value"])
    monkeypatch.setattr(
        "headroom.lean_ctx.get_lean_ctx_path",
        lambda: Path("/usr/bin/lean-ctx"),
    )
    monkeypatch.setattr(subprocess, "run", _fake_run)

    first = proxy_helpers._get_context_tool_stats()
    second = proxy_helpers._get_context_tool_stats()

    assert first == second
    assert first["tool"] == "lean-ctx"
    assert first["label"] == "lean-ctx"
    assert first["installed"] is True
    assert first["total_commands"] == 0
    assert first["tokens_saved"] == 0
    assert first["avg_savings_pct"] == 40.0
    assert first["session_savings_pct"] is None
    assert first["lifetime_total_commands"] == 3
    assert first["lifetime_input_tokens"] == 1000
    assert first["lifetime_output_tokens"] == 600
    assert first["lifetime_tokens_saved"] == 400
    assert calls["run"] == 1

    now["value"] += proxy_helpers.CONTEXT_TOOL_STATS_CACHE_TTL_SECONDS + 0.1
    third = proxy_helpers._get_context_tool_stats()

    assert third["tool"] == "lean-ctx"
    assert third["label"] == "lean-ctx"
    assert third["installed"] is True
    assert third["total_commands"] == 2
    assert third["input_tokens"] == 250
    assert third["output_tokens"] == 175
    assert third["tokens_saved"] == 75
    assert third["avg_savings_pct"] == 38.0
    assert third["avg_savings_pct_scope"] == "lifetime"
    assert third["session_savings_pct"] == 30.0
    assert third["lifetime_total_commands"] == 5
    assert third["lifetime_tokens_saved"] == 475
    assert third["session"]["savings_pct"] == 30.0
    assert calls["run"] == 2


def test_stats_cached_query_reuses_short_ttl_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    import headroom.proxy.server as server
    from headroom.proxy.server import ProxyConfig, create_app

    calls = {"store": 0, "telemetry": 0, "feedback": 0, "context_tool": 0}
    now = {"value": 100.0}

    monkeypatch.setattr(server.time, "monotonic", lambda: now["value"])
    monkeypatch.setattr(
        server,
        "get_compression_store",
        lambda: _StatsStub(calls, "store", {"entry_count": 1, "max_entries": 100}),
    )
    monkeypatch.setattr(
        server,
        "get_telemetry_collector",
        lambda: _StatsStub(calls, "telemetry", {"enabled": True}),
    )
    monkeypatch.setattr(
        server,
        "get_compression_feedback",
        lambda: _StatsStub(calls, "feedback", {}),
    )

    def _fake_context_tool_stats() -> dict[str, int | bool | float | str]:
        calls["context_tool"] += 1
        return {
            "tool": "rtk",
            "label": "RTK",
            "installed": True,
            "total_commands": 1,
            "tokens_saved": 5,
            "avg_savings_pct": 10.0,
        }

    monkeypatch.setattr(server, "_get_context_tool_stats", _fake_context_tool_stats)
    monkeypatch.setattr(server, "get_toin", lambda: _ToinStub())

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
        first = client.get("/stats?cached=1")
        second = client.get("/stats?cached=1")
        now["value"] += 5.1
        third = client.get("/stats?cached=1")
        uncached = client.get("/stats")

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 200
    assert uncached.status_code == 200

    assert calls == {"store": 3, "telemetry": 3, "feedback": 3, "context_tool": 3}
    assert first.json()["context_tool"]["configured"] == "rtk"
    assert first.json()["context_tool"]["label"] == "RTK"
    assert first.json()["cli_filtering"]["tokens_saved"] == 5
    assert first.json()["tokens"]["saved"] == 5
    assert first.json()["tokens"]["proxy_compression_saved"] == 0
    assert first.json()["tokens"]["cli_filtering_saved"] == 5
    assert first.json()["tokens"]["rtk_saved"] == 5
    assert first.json()["tokens"]["lean_ctx_saved"] == 0
    assert first.json()["tokens"]["all_layers_saved"] == 5
    assert (
        first.json()["tokens"]["savings_percent"]
        == first.json()["tokens"]["all_layers_savings_percent"]
    )
    assert first.json()["savings"]["by_layer"]["compression"]["tokens"] == 0
    assert first.json()["savings"]["by_layer"]["compression"]["cli_filtering_tokens"] == 5
    assert first.json()["savings"]["by_layer"]["compression"]["rtk_tokens"] == 5
    assert first.json()["savings"]["by_layer"]["compression"]["lean_ctx_tokens"] == 0
    assert first.json()["savings"]["by_layer"]["compression"]["all_layers_tokens"] == 5


def test_stats_reports_lean_ctx_as_selected_cli_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    import headroom.proxy.server as server
    from headroom.proxy.server import ProxyConfig, create_app

    monkeypatch.setattr(
        server,
        "get_compression_store",
        lambda: _StatsStub({"store": 0}, "store", {}),
    )
    monkeypatch.setattr(
        server,
        "get_telemetry_collector",
        lambda: _StatsStub({"telemetry": 0}, "telemetry", {}),
    )
    monkeypatch.setattr(
        server,
        "get_compression_feedback",
        lambda: _StatsStub({"feedback": 0}, "feedback", {}),
    )
    monkeypatch.setattr(
        server,
        "_get_context_tool_stats",
        lambda: {
            "tool": "lean-ctx",
            "label": "lean-ctx",
            "installed": True,
            "total_commands": 1,
            "tokens_saved": 9,
            "avg_savings_pct": 11.0,
        },
    )
    monkeypatch.setattr(server, "get_toin", lambda: _ToinStub())

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
        response = client.get("/stats")

    payload = response.json()
    assert response.status_code == 200
    assert payload["context_tool"]["configured"] == "lean-ctx"
    assert payload["savings"]["by_layer"]["cli_filtering"]["label"] == "lean-ctx"
    assert payload["tokens"]["cli_filtering_saved"] == 9
    assert payload["tokens"]["rtk_saved"] == 0
    assert payload["tokens"]["lean_ctx_saved"] == 9
    assert payload["savings"]["by_layer"]["compression"]["rtk_tokens"] == 0
    assert payload["savings"]["by_layer"]["compression"]["lean_ctx_tokens"] == 9


def test_cost_merge_uses_generic_cli_filtering_name() -> None:
    from headroom.proxy.cost import merge_cost_stats

    payload = merge_cost_stats(
        {"savings_usd": 1.23456, "other": "kept"},
        {"totals": {"net_savings_usd": 0.25}},
        cli_tokens_avoided=12,
    )

    assert payload is not None
    assert payload["compression_savings_usd"] == 1.2346
    assert payload["cache_savings_usd"] == 0.25
    assert payload["cli_tokens_avoided"] == 12
    assert payload["cli_filtering_tokens_avoided"] == 12
    assert payload["cli_filtering_tokens_included_in_compression"] is True
    assert payload["cli_tokens_included_in_compression"] is True


def test_session_summary_uses_generic_cli_filtering_keys() -> None:
    from headroom.proxy.cost import build_session_summary

    proxy = SimpleNamespace(
        config=SimpleNamespace(mode="token"),
        logger=SimpleNamespace(_logs=[]),
        cost_tracker=SimpleNamespace(
            stats=lambda: {
                "cost_with_headroom_usd": 2.0,
                "savings_usd": 0.5,
            }
        ),
    )
    metrics = SimpleNamespace(
        requests_by_model={"gpt-test": 1},
        tokens_saved_total=20,
    )

    payload = build_session_summary(
        proxy,
        metrics,
        {"totals": {"net_savings_usd": 0.2}},
        cli_tokens_avoided=7,
        total_tokens_before=100,
    )

    assert payload["compression"]["cli_filtering_tokens_avoided"] == 7
    assert payload["compression"]["total_tokens_saved_with_cli_filtering"] == 27
    assert payload["compression"]["total_tokens_before_with_cli_filtering"] == 100
    assert payload["compression"]["rtk_tokens_avoided"] == 7
    assert payload["cost"]["breakdown"]["cli_filtering_savings_usd"] is None
    assert payload["cost"]["breakdown"]["rtk_savings_usd"] is None


def test_stats_reset_clears_runtime_proxy_counters(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    import headroom.proxy.server as server
    from headroom.proxy.loopback_guard import require_loopback
    from headroom.proxy.server import ProxyConfig, create_app

    monkeypatch.setattr(
        server,
        "get_compression_store",
        lambda: _StatsStub({"store": 0}, "store", {}),
    )
    monkeypatch.setattr(
        server,
        "get_telemetry_collector",
        lambda: _StatsStub({"telemetry": 0}, "telemetry", {}),
    )
    monkeypatch.setattr(
        server,
        "get_compression_feedback",
        lambda: _StatsStub({"feedback": 0}, "feedback", {}),
    )
    monkeypatch.setattr(server, "_get_context_tool_stats", lambda: None)
    monkeypatch.setattr(server, "get_toin", lambda: _ToinStub())

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
    app.dependency_overrides[require_loopback] = lambda: None

    with TestClient(app) as client:
        proxy = client.app.state.proxy
        proxy.metrics.tokens_saved_total = 123
        proxy.metrics.tokens_input_total = 456
        proxy.metrics.requests_total = 2

        before = client.get("/stats").json()
        reset = client.post("/stats/reset")
        after = client.get("/stats").json()

    assert before["tokens"]["proxy_compression_saved"] == 123
    assert reset.status_code == 200
    assert after["tokens"]["proxy_compression_saved"] == 0
    assert after["tokens"]["input"] == 0
    assert after["requests"]["total"] == 0


def test_dashboard_uses_cached_stats_and_lazy_history_feed_polling() -> None:
    html = get_dashboard_html()

    assert "fetch('/stats?cached=1')" in html
    assert "@click=\"setViewMode('history')\"" in html
    assert '@click="toggleFeed()"' in html
    assert "this.viewMode === 'history'" in html
    assert "this.feedOpen" in html
    assert "CLI Filtering (rtk)" not in html
    assert "RTK Filtered" not in html
    assert "|| 'RTK'" not in html
    assert "rtkShareOfTotal" not in html
    assert "Lean-ctx" in html
    assert "Context Tool" in html
    assert "Before Headroom layers" in html
    assert "Proxy input after RTK" in html
    assert "Proxy removed" in html
    assert "Sent upstream" in html
    assert "Output tokens" in html
    assert "Before Compression" not in html
    assert "After Compression (sent)" not in html
    assert "cliFilteringLabel + ' filtered this session'" in html
    assert "cliFilteringLabel + ' filtered'" in html
    assert "cliFilteringLabel + ' lifetime'" in html
    assert "session delta unavailable" in html
    assert "session_delta_available" in html
    assert "showCliFilteringLifetimeLine" in html
    assert "this.cliFilteringLifetime !== this.cliFilteringSessionValue" in html
    assert "proxy_total_before_compression" in html


def test_dashboard_proxy_dollars_use_current_proxy_cost_not_lifetime_total() -> None:
    html = get_dashboard_html()

    hero_card = html[html.index("Proxy $ Saved") : html.index("Token Savings")]
    assert "formatSessionProxyCurrency(" in hero_card
    assert "stats.summary?.cost?.breakdown?.compression_savings_usd" in hero_card
    assert "stats.summary?.cost?.total_saved_usd" in hero_card
    assert "stats.persistent_savings?.lifetime?.compression_savings_usd" not in hero_card


def test_dashboard_proxy_dollars_show_sub_cent_positive_savings() -> None:
    html = get_dashboard_html()

    assert "formatSessionProxyCurrency(n)" in html
    assert "if (n > 0 && n < 0.01) return '<$0.01';" in html


def test_dashboard_output_shaper_card_falls_back_to_applied_activity() -> None:
    html = get_dashboard_html()

    assert "stats.savings?.by_layer?.output_shaping?.applied_requests" in html
    assert "shaped responses · steering applied" in html


def test_dashboard_output_shaper_uses_estimate_quality_not_negative_saved_headline() -> None:
    html = get_dashboard_html()
    start = html.index("Output Shaping (counterfactual)")
    output_card = html[start : start + 5000]

    assert "estimate_quality" in output_card
    assert "estimate_status" in output_card
    assert "estimate_reliable" in output_card
    assert "estimate_reasons" in output_card
    assert "display_tokens_saved" in output_card
    assert "? 'Output Tokens Saved' : 'Output Shaping'" in output_card
    assert "Applied steering" in output_card
    assert "' shaped responses · '" in output_card
    assert "'estimate ' + (stats.tokens.output_reduction.estimate_quality" in output_card
    assert 'x-show="stats.tokens?.output_reduction?.estimate_reliable &&' in output_card
    assert "estimated counterfactual" in output_card


def _stats_payload_with_output_estimate(
    monkeypatch: pytest.MonkeyPatch, estimate: SimpleNamespace
) -> dict:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    import headroom.proxy.output_savings as output_savings
    import headroom.proxy.server as server
    from headroom.proxy.server import ProxyConfig, create_app

    monkeypatch.setenv("HEADROOM_OUTPUT_SHAPER", "1")

    class _Recorder:
        def estimate(self) -> SimpleNamespace:
            return estimate

    monkeypatch.setattr(output_savings, "get_recorder", lambda: _Recorder())
    monkeypatch.setattr(
        server, "get_compression_store", lambda: _StatsStub({"store": 0}, "store", {})
    )
    monkeypatch.setattr(
        server, "get_telemetry_collector", lambda: _StatsStub({"telemetry": 0}, "telemetry", {})
    )
    monkeypatch.setattr(
        server, "get_compression_feedback", lambda: _StatsStub({"feedback": 0}, "feedback", {})
    )
    monkeypatch.setattr(server, "_get_context_tool_stats", lambda: {})
    monkeypatch.setattr(server, "get_toin", lambda: _ToinStub())

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
        return client.get("/stats").json()


def test_stats_exact_live_bad_output_estimate_keeps_raw_fields_but_hides_display_savings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _stats_payload_with_output_estimate(
        monkeypatch,
        SimpleNamespace(
            n_requests=9,
            kind="estimated",
            tokens_saved=-4852,
            baseline_tokens=470,
            pct=-687.9,
            ci_low_pct=-2232.0,
            ci_high_pct=856.3,
            estimate_reliable=False,
            estimate_status="warming",
            estimate_reasons=["low_sample", "inconclusive", "negative", "unstable"],
        ),
    )

    output = payload["tokens"]["output_reduction"]
    assert output["tokens_saved"] == -4852
    assert output["baseline_tokens"] == 470
    assert output["reduction_percent"] == -687.9
    assert output["ci_low_percent"] == -2232.0
    assert output["ci_high_percent"] == 856.3
    assert output["estimate_reliable"] is False
    assert output["estimate_status"] == "warming"
    assert output["estimate_quality"] == "warming"
    assert output["estimate_reasons"] == ["low_sample", "inconclusive", "negative", "unstable"]
    assert output["display_tokens_saved"] is None
    assert output["display_reduction_percent"] is None


def test_stats_ci_crossing_zero_marks_output_estimate_inconclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _stats_payload_with_output_estimate(
        monkeypatch,
        SimpleNamespace(
            n_requests=30,
            kind="estimated",
            tokens_saved=120,
            baseline_tokens=1000,
            pct=12.0,
            ci_low_pct=-4.0,
            ci_high_pct=28.0,
            estimate_reliable=False,
            estimate_status="inconclusive",
            estimate_reasons=["inconclusive"],
        ),
    )

    output = payload["tokens"]["output_reduction"]
    assert output["estimate_status"] == "inconclusive"
    assert output["estimate_reliable"] is False
    assert output["estimate_reasons"] == ["inconclusive"]
    assert output["display_tokens_saved"] is None


def test_stats_negative_output_estimate_does_not_render_tokens_saved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _stats_payload_with_output_estimate(
        monkeypatch,
        SimpleNamespace(
            n_requests=30,
            kind="estimated",
            tokens_saved=-100,
            baseline_tokens=1000,
            pct=-10.0,
            ci_low_pct=-12.0,
            ci_high_pct=-8.0,
            estimate_reliable=False,
            estimate_status="negative",
            estimate_reasons=["negative"],
        ),
    )

    output = payload["tokens"]["output_reduction"]
    assert output["tokens_saved"] == -100
    assert output["estimate_status"] == "negative"
    assert output["estimate_reliable"] is False
    assert output["estimate_reasons"] == ["negative"]
    assert output["display_tokens_saved"] is None


def test_stats_stable_positive_output_estimate_renders_display_savings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _stats_payload_with_output_estimate(
        monkeypatch,
        SimpleNamespace(
            n_requests=30,
            kind="estimated",
            tokens_saved=240,
            baseline_tokens=1000,
            pct=24.0,
            ci_low_pct=18.0,
            ci_high_pct=30.0,
            estimate_reliable=True,
            estimate_status="stable",
            estimate_reasons=[],
        ),
    )

    output = payload["tokens"]["output_reduction"]
    assert output["estimate_status"] == "stable"
    assert output["estimate_reliable"] is True
    assert output["estimate_reasons"] == []
    assert output["display_tokens_saved"] == 240
    assert output["display_reduction_percent"] == 24.0


def test_dashboard_session_metrics_do_not_repeat_proxy_tokens_without_new_context() -> None:
    html = get_dashboard_html()

    assert "proxy tokens removed" not in html
    assert '<span class="text-sm text-gray-400">Headroom Overhead</span>' not in html
    assert '<span class="text-sm text-gray-400">TTFB (upstream)</span>' not in html
    assert "Overhead Range" in html
    assert "TTFB Range" in html
    assert "Proxy Removed" in html


def test_proxy_throughput_in_stats_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that the /stats endpoint includes a 'throughput' key in the response.

    The server's _compute_throughput closure does a fresh
    `from headroom.perf.analyzer import ...` on every call, so we patch the
    names directly on the `headroom.perf.analyzer` module so the local import
    inside the closure picks up our fakes.

    Skipped locally when headroom._core (Rust extension) is not compiled.
    """
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    import headroom.perf.analyzer as _analyzer_mod

    try:
        from headroom.proxy.server import (
            _throughput_cache,
            create_app,
            require_loopback,
        )
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.skip(f"headroom._core not available (Rust extension not compiled): {exc}")

    from headroom.config import ProxyConfig

    # Reset the module-level cache so CI doesn't reuse a stale value
    _throughput_cache.update({"expires_at": 0.0, "value": None})

    # Patch at the module level so the local import inside _compute_throughput
    # picks up our stubs instead of the real implementations.
    monkeypatch.setattr(
        _analyzer_mod,
        "parse_log_files",
        lambda last_n_hours=1.0: _analyzer_mod.PerfReport(),
    )
    monkeypatch.setattr(
        _analyzer_mod,
        "build_perf_summary",
        lambda report: {"throughput": {"input_wall_clock": 99.0}},
    )

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
    app.dependency_overrides[require_loopback] = lambda: None

    with TestClient(app) as client:
        response = client.get("/stats")

    assert response.status_code == 200
    payload = response.json()
    assert "throughput" in payload
    assert payload["throughput"] == {"input_wall_clock": 99.0}


def test_stats_output_shaping_reports_recent_codex_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    import headroom.proxy.output_savings as output_savings
    import headroom.proxy.server as server
    from headroom.proxy.models import RequestLog
    from headroom.proxy.request_logger import RequestLogger
    from headroom.proxy.server import ProxyConfig, create_app

    monkeypatch.setenv("HEADROOM_OUTPUT_SHAPER", "1")

    class _NoOutputSavingsRecorder:
        def estimate(self):
            return type("Estimate", (), {"n_requests": 0})()

    monkeypatch.setattr(output_savings, "get_recorder", lambda: _NoOutputSavingsRecorder())
    calls = {"store": 0, "telemetry": 0, "feedback": 0}
    monkeypatch.setattr(
        server,
        "get_compression_store",
        lambda: _StatsStub(calls, "store", {"entry_count": 0, "max_entries": 100}),
    )
    monkeypatch.setattr(
        server,
        "get_telemetry_collector",
        lambda: _StatsStub(calls, "telemetry", {"enabled": True}),
    )
    monkeypatch.setattr(
        server,
        "get_compression_feedback",
        lambda: _StatsStub(calls, "feedback", {}),
    )
    monkeypatch.setattr(server, "_get_context_tool_stats", lambda: {})
    monkeypatch.setattr(server, "get_toin", lambda: _ToinStub())

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
    app.state.proxy.logger = RequestLogger(log_file=None, log_full_messages=False)
    app.state.proxy.logger.log(
        RequestLog(
            request_id="r1",
            timestamp="2026-06-21T19:20:00Z",
            provider="openai",
            model="gpt-5.5",
            input_tokens_original=100,
            input_tokens_optimized=90,
            output_tokens=10,
            tokens_saved=10,
            savings_percent=10.0,
            optimization_latency_ms=1.0,
            total_latency_ms=20.0,
            tags={"client": "codex"},
            cache_hit=False,
            transforms_applied=["output_shaper:verbosity:L2"],
        )
    )

    with TestClient(app) as client:
        payload = client.get("/stats").json()

    output_shaping = payload["savings"]["by_layer"]["output_shaping"]
    assert output_shaping["enabled"] is True
    assert output_shaping["applied"] is True
    assert output_shaping["available"] is True
    assert output_shaping["estimate_available"] is False
    assert output_shaping["method"] == "request_steering"
    assert output_shaping["applied_requests"] == 1
    assert output_shaping["level_counts"] == {"L2": 1}
    assert output_shaping["by_client"] == {"codex": 1}
    assert output_shaping["latest_label"] == "output_shaper:verbosity:L2"


def test_output_shaping_control_label_does_not_count_as_applied_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HEADROOM_OUTPUT_SHAPER", "1")
    from fastapi.testclient import TestClient

    from headroom.proxy.request_logger import RequestLog, RequestLogger
    from headroom.proxy.server import ProxyConfig, create_app

    app = create_app(
        ProxyConfig(
            optimize=False,
            cost_tracking_enabled=False,
            log_requests=False,
            ccr_inject_tool=False,
            ccr_handle_responses=False,
        )
    )
    app.state.proxy.logger = RequestLogger(log_file=None, log_full_messages=False)
    app.state.proxy.logger.log(
        RequestLog(
            request_id="control",
            timestamp="2026-06-23T00:00:00Z",
            provider="openai",
            model="gpt-5.4",
            input_tokens_original=10,
            input_tokens_optimized=10,
            output_tokens=1,
            tokens_saved=0,
            savings_percent=0.0,
            optimization_latency_ms=0.0,
            total_latency_ms=1.0,
            transforms_applied=["output_shaper:control:tiny"],
            tags={"client": "codex"},
            cache_hit=False,
        )
    )
    app.state.proxy.logger.log(
        RequestLog(
            request_id="shaped",
            timestamp="2026-06-23T00:00:01Z",
            provider="openai",
            model="gpt-5.4",
            input_tokens_original=10,
            input_tokens_optimized=10,
            output_tokens=1,
            tokens_saved=0,
            savings_percent=0.0,
            optimization_latency_ms=0.0,
            total_latency_ms=1.0,
            transforms_applied=["output_shaper:verbosity:L2"],
            tags={"client": "codex"},
            cache_hit=False,
        )
    )

    with TestClient(app) as client:
        output_shaping = client.get("/stats").json()["savings"]["by_layer"]["output_shaping"]

    assert output_shaping["applied_requests"] == 1
    assert output_shaping["level_counts"] == {"L2": 1}
    assert output_shaping["latest_label"] == "output_shaper:verbosity:L2"
