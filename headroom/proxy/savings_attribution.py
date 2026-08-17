"""Bounded attribution for savings that do not have a built-in metric."""

from __future__ import annotations

import base64
import json
import re
from collections.abc import MutableMapping
from typing import Any

SAVINGS_ATTRIBUTION_TAG = "_headroom_savings_attribution"
_NAME_RE = re.compile(r"[^a-z0-9_.-]+")
MAX_SOURCES = 32
_SCOPE_KEY = "headroom_savings_attribution"


def _source_name(value: object) -> str:
    name = _NAME_RE.sub("_", str(value or "other").strip().lower()).strip("_.-")
    return (name or "other")[:64]


def _ledger(tags: MutableMapping[str, Any]) -> list[dict[str, Any]]:
    current = tags.get(SAVINGS_ATTRIBUTION_TAG)
    if isinstance(current, list):
        return current
    current = []
    tags[SAVINGS_ATTRIBUTION_TAG] = current
    return current


def bind_scope(tags: MutableMapping[str, Any], scope: MutableMapping[str, Any]) -> None:
    """Share one ledger between ASGI middleware and the request handler."""
    state = scope.setdefault("state", {})
    ledger = state.get(_SCOPE_KEY)
    if not isinstance(ledger, list):
        ledger = []
        state[_SCOPE_KEY] = ledger
    tags[SAVINGS_ATTRIBUTION_TAG] = ledger


def record_scope_savings(scope: MutableMapping[str, Any], source: object, **values: Any) -> None:
    state = scope.setdefault("state", {})
    ledger = state.get(_SCOPE_KEY)
    if not isinstance(ledger, list):
        ledger = []
        state[_SCOPE_KEY] = ledger
    record_savings({SAVINGS_ATTRIBUTION_TAG: ledger}, source, **values)


def record_savings(
    tags: MutableMapping[str, Any],
    source: object,
    *,
    tokens: int = 0,
    usd: float = 0.0,
    realized: bool = True,
    estimated: bool = False,
    details: dict[str, Any] | None = None,
) -> None:
    """Attribute savings to a source; this never changes headline totals."""
    ledger = _ledger(tags)
    if len(ledger) >= MAX_SOURCES:
        return
    item: dict[str, Any] = {
        "source": _source_name(source),
        "realized": bool(realized),
        "estimated": bool(estimated),
        "tokens": max(0, int(tokens or 0)),
        "usd": round(float(usd or 0.0), 12),
    }
    if details:
        item["details"] = {
            _source_name(key): value
            for key, value in list(details.items())[:12]
            if isinstance(value, (str, int, float, bool)) or value is None
        }
    ledger.append(item)


def from_tags(tags: MutableMapping[str, Any] | None) -> list[dict[str, Any]]:
    raw = (tags or {}).get(SAVINGS_ATTRIBUTION_TAG)
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw[:MAX_SOURCES] if isinstance(item, dict)]


def public_tags(tags: MutableMapping[str, Any] | None) -> dict[str, Any]:
    return {key: value for key, value in (tags or {}).items() if key != SAVINGS_ATTRIBUTION_TAG}


def encode(items: list[dict[str, Any]]) -> str:
    if not items:
        return "none"
    payload = json.dumps(items, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode(value: str) -> list[dict[str, Any]]:
    if not value or value == "none":
        return []
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded).decode())
    except Exception:
        return []
    return (
        [dict(item) for item in decoded if isinstance(item, dict)]
        if isinstance(decoded, list)
        else []
    )
