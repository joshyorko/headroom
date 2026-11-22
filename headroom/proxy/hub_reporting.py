"""Read-only CLIProxyAPI reporting endpoints used by the T3 usage reader."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from headroom.subscription.base import QuotaTrackerRegistry

CLAUDE_AUTH_INDEX = "headroom-claude"
CODEX_AUTH_INDEX = "headroom-codex"
CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CODEX_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
CODEX_CREDITS_URL = "https://chatgpt.com/backend-api/wham/rate-limit-reset-credits"


def _response(status_code: int, payload: Any) -> dict[str, Any]:
    return {"status_code": status_code, "body": json.dumps(payload, separators=(",", ":"))}


def list_auth_files(registry: QuotaTrackerRegistry) -> dict[str, Any]:
    """Describe available provider trackers, without pretending to export credentials."""
    files = []
    for auth_index, (key, provider, _, convert) in _ACCOUNTS.items():
        stats = _stats(registry, key)
        if stats is not None and convert(stats) is not None:
            files.append(
                {
                    "id": auth_index,
                    "auth_index": auth_index,
                    "provider": provider,
                    "disabled": False,
                }
            )
    return {"files": files}


def _stats(registry: QuotaTrackerRegistry, key: str) -> dict[str, Any] | None:
    tracker = registry.get(key)
    if tracker is None or not tracker.is_available():
        return None
    stats = tracker.get_stats()
    return stats if isinstance(stats, dict) else None


def _not_expired(window: dict[str, Any]) -> bool:
    reset = window.get("resets_at")
    if reset in (None, ""):
        return True
    try:
        if isinstance(reset, (int, float)):
            return float(reset) > datetime.now(timezone.utc).timestamp()
        parsed = datetime.fromisoformat(str(reset).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp() > datetime.now(timezone.utc).timestamp()
    except (TypeError, ValueError, OverflowError):
        # An unparseable reset is unknown, not proof that the snapshot expired.
        return True


def _claude_usage(stats: dict[str, Any]) -> dict[str, Any] | None:
    latest = stats.get("latest")
    if not isinstance(latest, dict):
        return None
    usage: dict[str, Any] = {}
    for name in ("five_hour", "seven_day"):
        source = latest.get(name)
        if isinstance(source, dict) and "utilization_pct" in source and _not_expired(source):
            usage[name] = {
                "utilization": source["utilization_pct"],
                "resets_at": source.get("resets_at"),
            }
    scoped = []
    for name, display_name in (("seven_day_opus", "opus"), ("seven_day_sonnet", "sonnet")):
        source = latest.get(name)
        if isinstance(source, dict) and _not_expired(source) and "utilization_pct" in source:
            item = {
                "kind": "weekly_scoped",
                "percent": source["utilization_pct"],
                "scope": {"model": {"display_name": display_name}},
            }
            if "resets_at" in source:
                item["resets_at"] = source["resets_at"]
            scoped.append(item)
    if scoped:
        usage["limits"] = scoped
    return usage or None


def _codex_usage(stats: dict[str, Any]) -> dict[str, Any] | None:
    rate_limit: dict[str, Any] = {}
    for name in ("primary", "secondary"):
        source = stats.get(name)
        if not isinstance(source, dict) or "used_percent" not in source:
            continue
        reset = source.get("resets_at")
        if reset is not None and float(reset) <= datetime.now(timezone.utc).timestamp():
            continue
        window: dict[str, Any] = {"used_percent": source["used_percent"]}
        minutes = source.get("window_minutes")
        if minutes is not None:
            window["limit_window_seconds"] = int(minutes * 60)
        if reset is not None:
            window["reset_at"] = reset
        rate_limit[f"{name}_window"] = window
    return {"rate_limit": rate_limit} if rate_limit else None


_ACCOUNTS = {
    CLAUDE_AUTH_INDEX: ("subscription_window", "claude", CLAUDE_USAGE_URL, _claude_usage),
    CODEX_AUTH_INDEX: ("codex_rate_limits", "codex", CODEX_USAGE_URL, _codex_usage),
}


def report_api_call(
    registry: QuotaTrackerRegistry,
    *,
    auth_index: str,
    method: str,
    url: str,
) -> dict[str, Any]:
    """Serve only the two exact provider usage GETs; never makes network calls."""
    account = _ACCOUNTS.get(auth_index)
    if account is None:
        return _response(404, {"error": "unknown account"})
    if method.upper() != "GET":
        return _response(405, {"error": "method not allowed"})
    if auth_index == CODEX_AUTH_INDEX and url == CODEX_CREDITS_URL:
        return _response(501, {"error": "reset credits are not reported"})
    key, _, allowed_url, convert = account
    if url != allowed_url:
        return _response(403, {"error": "unsupported URL"})
    stats = _stats(registry, key)
    usage = convert(stats) if stats is not None else None
    if usage is None:
        return _response(503, {"error": "usage data unavailable"})
    return _response(200, usage)
