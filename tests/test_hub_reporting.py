"""Read-only CLIProxyAPI reporting adapter for the T3 usage reader."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from headroom.proxy.hub_reporting import list_auth_files, report_api_call
from headroom.subscription.base import QuotaTracker, QuotaTrackerRegistry


class _Tracker(QuotaTracker):
    label = "test"

    def __init__(self, key: str, stats: dict | None, available: bool = True):
        self._key, self._stats, self._available = key, stats, available

    @property
    def key(self) -> str:
        return self._key

    def is_available(self) -> bool:
        return self._available

    def get_stats(self):
        return self._stats


def _registry(**trackers):
    registry = QuotaTrackerRegistry()
    for key, (stats, available) in trackers.items():
        registry.register(_Tracker(key, stats, available))
    return registry


def _payload(response: dict):
    return json.loads(response["body"])


def test_list_auth_files_has_fixed_supported_accounts_without_identity_secrets():
    registry = _registry(subscription_window=(None, True), codex_rate_limits=(None, True))
    assert list_auth_files(registry) == {
        "files": [
            {
                "id": "headroom-claude",
                "auth_index": "headroom-claude",
                "provider": "claude",
                "disabled": False,
            },
            {
                "id": "headroom-codex",
                "auth_index": "headroom-codex",
                "provider": "codex",
                "disabled": False,
            },
        ]
    }


def test_list_auth_files_omits_unregistered_and_unavailable_trackers():
    registry = _registry(subscription_window=(None, False), codex_rate_limits=(None, True))
    assert [item["provider"] for item in list_auth_files(registry)["files"]] == ["codex"]
    assert list_auth_files(_registry()) == {"files": []}


def test_claude_window_without_utilization_is_unavailable():
    registry = _registry(subscription_window=({"latest": {"five_hour": {"resets_at": None}}}, True))
    assert (
        report_api_call(
            registry,
            auth_index="headroom-claude",
            method="GET",
            url="https://api.anthropic.com/api/oauth/usage",
        )["status_code"]
        == 503
    )


def test_claude_report_maps_subscription_windows_and_weekly_model_limits():
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    stats = {
        "latest": {
            "five_hour": {"utilization_pct": 21.5, "resets_at": future},
            "seven_day": {"utilization_pct": 32, "resets_at": future},
            "seven_day_opus": {"utilization_pct": 43, "resets_at": future},
            "seven_day_sonnet": {"utilization_pct": 54, "resets_at": future},
        }
    }
    response = report_api_call(
        _registry(subscription_window=(stats, True)),
        auth_index="headroom-claude",
        method="GET",
        url="https://api.anthropic.com/api/oauth/usage",
    )
    body = _payload(response)
    assert response["status_code"] == 200
    assert body["five_hour"] == {"utilization": 21.5, "resets_at": future}
    assert body["seven_day"] == {"utilization": 32, "resets_at": future}
    assert body["limits"] == [
        {
            "kind": "weekly_scoped",
            "percent": 43,
            "resets_at": future,
            "scope": {"model": {"display_name": "opus"}},
        },
        {
            "kind": "weekly_scoped",
            "percent": 54,
            "resets_at": future,
            "scope": {"model": {"display_name": "sonnet"}},
        },
    ]


def test_claude_expired_windows_are_omitted_without_synthetic_zero_values():
    past = (datetime.now(timezone.utc) - timedelta(seconds=2)).isoformat()
    stats = {"latest": {"five_hour": {"utilization_pct": 99, "resets_at": past}}}
    body = _payload(
        report_api_call(
            _registry(subscription_window=(stats, True)),
            auth_index="headroom-claude",
            method="GET",
            url="https://api.anthropic.com/api/oauth/usage",
        )
    )
    assert "five_hour" not in body


def test_codex_report_maps_present_windows_and_omits_unknown_plan():
    future = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
    stats = {
        "primary": {"used_percent": 12, "window_minutes": 300, "resets_at": future},
        "secondary": {"used_percent": 34, "window_minutes": 10080, "resets_at": None},
    }
    response = report_api_call(
        _registry(codex_rate_limits=(stats, True)),
        auth_index="headroom-codex",
        method="GET",
        url="https://chatgpt.com/backend-api/wham/usage",
    )
    body = _payload(response)
    assert response["status_code"] == 200
    assert "plan_type" not in body
    assert body["rate_limit"] == {
        "primary_window": {"used_percent": 12, "limit_window_seconds": 18000, "reset_at": future},
        "secondary_window": {"used_percent": 34, "limit_window_seconds": 604800},
    }


@pytest.mark.parametrize("auth_index", ["unknown", "headroom-copilot"])
def test_unknown_accounts_return_inner_404(auth_index):
    assert (
        report_api_call(
            _registry(),
            auth_index=auth_index,
            method="GET",
            url="https://api.anthropic.com/api/oauth/usage",
        )["status_code"]
        == 404
    )


def test_non_get_unsupported_url_and_reset_credits_fail_closed():
    args = {"auth_index": "headroom-codex", "url": "https://chatgpt.com/backend-api/wham/usage"}
    assert report_api_call(_registry(), method="POST", **args)["status_code"] == 405
    assert (
        report_api_call(
            _registry(), method="GET", url="https://example.com", auth_index="headroom-codex"
        )["status_code"]
        == 403
    )
    assert (
        report_api_call(
            _registry(),
            method="GET",
            url="https://chatgpt.com/backend-api/wham/rate-limit-reset-credits",
            auth_index="headroom-codex",
        )["status_code"]
        == 501
    )


def test_missing_or_unavailable_snapshot_returns_503():
    for stats, available in ((None, True), ({"latest": None}, True), ({"latest": None}, False)):
        result = report_api_call(
            _registry(subscription_window=(stats, available)),
            auth_index="headroom-claude",
            method="GET",
            url="https://api.anthropic.com/api/oauth/usage",
        )
        assert result["status_code"] == 503
