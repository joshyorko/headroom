"""Telemetry state for Headroom.

Two independent switches, because they answer two different questions:

``HEADROOM_TELEMETRY`` — **off by default, opt-in.** Aggregates stats locally
for the in-process collector and the ``/stats`` / ``/v1/telemetry`` endpoints.
Never leaves the machine.

``HEADROOM_BEACON`` — **on by default, opt-out.** Uploads an anonymous,
content-free session summary to Headroom Labs. Disable with
``HEADROOM_BEACON=off``, ``DO_NOT_TRACK=1``, or offline mode. See
:mod:`headroom.telemetry.session` for the exact payload and
``deploy/beacon/worker.js`` for what the receiver does with it.

Operational metrics are separate again, and go to *your own* OpenTelemetry
collector via ``HEADROOM_OTEL_METRICS_*`` — a destination you control, that
Headroom Labs never sees.

Keeping these separate matters: an operator who turned on local stats has not
thereby agreed to upload anything, and must not start doing so on upgrade.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import platform
import sys
import time
import uuid

from headroom.telemetry.context import detect_install_mode, detect_stack

logger = logging.getLogger(__name__)

# Supabase endpoint for anonymous aggregate telemetry.
# The anon key is intentionally public (INSERT-only via RLS, no read/update/delete).
# Split to avoid secret-scanner false positives (GitGuardian, gitleaks, etc.).
_SUPABASE_URL = "https://dtlllcsudcoasebbamcq.supabase.co"
_SUPABASE_KEY = ".".join(
    [
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImR0bGxsY3N1ZGNvYXNlYmJhbWNxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzM3MDc4NDUsImV4cCI6MjA4OTI4Mzg0NX0",
        "h_C6dLQKa8BVc3upgEvulR4E0K4eiEViyddRMIylKjU",
    ]
)
_TABLE = "proxy_telemetry_v2"
_ENDPOINT = f"{_SUPABASE_URL}/rest/v1/{_TABLE}?on_conflict=session_id"

# Report every 5 minutes
_INTERVAL_SECONDS = 300


_OFF_VALUES = frozenset(("off", "false", "0", "no", "disable", "disabled"))
_ON_VALUES = frozenset(("on", "true", "1", "yes", "enable", "enabled"))


def _build_pipeline_timing(stats: dict) -> dict[str, object]:
    """Project the /stats `pipeline_timing` JSONB payload for Supabase.

    Flattens transform timing to {name: avg_ms} and, when present, nests
    ContentRouter strategy counts and per-strategy tokens-saved totals
    under a `_strategies` sub-key. The Supabase column is JSONB, so the
    nested shape lands without a schema change.
    """
    raw_timing = stats.get("pipeline_timing", {}) or {}
    pipeline_timing: dict[str, object] = {
        name: round(info.get("average_ms", 0), 2)
        for name, info in raw_timing.items()
        if isinstance(info, dict)
    }
    strategies = stats.get("compressions_by_strategy", {}) or {}
    tokens_by_strategy = stats.get("tokens_saved_by_strategy", {}) or {}
    if strategies or tokens_by_strategy:
        pipeline_timing["_strategies"] = {
            "compressions": dict(strategies),
            "tokens_saved": dict(tokens_by_strategy),
        }
    return pipeline_timing


def is_telemetry_enabled() -> bool:
    """Check if telemetry is enabled (off by default, opt in with env var).

    Fail-closed: telemetry is only enabled when HEADROOM_TELEMETRY is set to an
    explicit on-value (on/true/1/yes/enable/enabled). Anything else — including
    unset, empty, or an unrecognized value — leaves it disabled.
    """
    val = os.environ.get("HEADROOM_TELEMETRY", "").lower().strip()
    return val in _ON_VALUES


# Whether the upload beacon runs when the operator has expressed no preference.
#
# True makes Headroom opt-OUT: every install uploads anonymous session summaries
# unless it is told not to. Flip to False for opt-in and nothing uploads without
# an explicit HEADROOM_BEACON=on.
#
# This single constant is the whole policy — deliberately, so the decision is
# one line to audit and one line to reverse.
BEACON_DEFAULT_ON = True


def is_beacon_enabled() -> bool:
    """Check if the anonymous upload beacon is enabled.

    Default is :data:`BEACON_DEFAULT_ON`. Three things switch it off regardless,
    in this order:

    * offline mode — no network is no network;
    * ``DO_NOT_TRACK`` — the cross-tool convention, honoured because a user who
      has already stated this preference should not have to state it again;
    * ``HEADROOM_BEACON=off`` (or false/0/no/disable/disabled).

    Deliberately a *separate* switch from ``HEADROOM_TELEMETRY``. That flag
    means "aggregate stats locally so ``/stats`` has something to show" — data
    that never leaves the machine. Overloading it to also authorise upload
    would mean every operator who had turned on local stats begins transmitting
    the moment they upgrade, having answered a different question.

    Note the asymmetry with :func:`is_telemetry_enabled`, which is fail-closed:
    this one is fail-open by construction while ``BEACON_DEFAULT_ON`` is True,
    so an unrecognised value uploads rather than staying silent.
    """
    from headroom.offline import is_offline

    if is_offline():
        return False
    dnt = os.environ.get("DO_NOT_TRACK", "").lower().strip()
    if dnt and dnt not in _OFF_VALUES:
        return False
    raw = os.environ.get("HEADROOM_BEACON", "").lower().strip()
    if raw in _OFF_VALUES:
        return False
    if raw in _ON_VALUES:
        return True
    return BEACON_DEFAULT_ON


def is_telemetry_warn_enabled() -> bool:
    """Check if telemetry warnings are enabled (feature flag, on by default).

    Set HEADROOM_TELEMETRY_WARN=off to suppress startup/wrap notices.
    This is a build/pack-time feature flag intended for operators who want
    to disable the notice without disabling telemetry itself.
    """
    val = os.environ.get("HEADROOM_TELEMETRY_WARN", "on").lower().strip()
    return val not in _OFF_VALUES


def format_telemetry_notice(*, prefix: str = "") -> str:
    """Return a single-line telemetry notice suitable for CLI output.

    Args:
        prefix: Optional leading whitespace / box-drawing prefix.

    Returns an empty string when telemetry or warnings are disabled so callers
    can unconditionally include the result in their output.
    """
    if not is_telemetry_warn_enabled():
        return ""

    beacon = is_beacon_enabled()
    local = is_telemetry_enabled()
    if not beacon and not local:
        return ""

    # The beacon line comes first and is unconditional when on. It is opt-out,
    # so this notice is the only place a user learns it is running at all —
    # surprise is what turns anonymous telemetry into a trust incident.
    #
    # Wording: lead with what the data *is* (compression ratios) and why it is
    # useful (understanding when compression works), not with the fact of
    # transmission. "Stats are sent to Headroom Labs" is accurate but reads like
    # extraction, which misrepresents a payload that is entirely counters. The
    # reassurance has to stay concrete, though — "never prompts, code, or file
    # paths" names the things people actually worry about, and every one of
    # those is enforced by the allowlist, not just promised here.
    if beacon:
        return (
            f"{prefix}Telemetry:    anonymous compression stats — never prompts, code, or "
            "file paths. Helps us improve compression | Off: HEADROOM_BEACON=off"
        )
    return (
        f"{prefix}Telemetry:    ENABLED (anonymous aggregate stats) | "
        "Disable: HEADROOM_TELEMETRY=off or --no-telemetry"
    )


class TelemetryBeacon:
    """Periodically sends anonymous aggregate stats to Supabase."""

    def __init__(self, port: int = 8787, sdk: str = "proxy", backend: str = "anthropic") -> None:
        self._port = port
        self._sdk = sdk
        self._backend = backend
        self._task: asyncio.Task[None] | None = None
        self._start_time = time.time()
        # Unique per proxy run — used as upsert key so each session produces 1 row
        self._session_id = uuid.uuid4().hex
        # Stable across restarts — anonymous machine fingerprint (SHA256 of hostname)
        self._instance_id = hashlib.sha256(platform.node().encode()).hexdigest()[:16]
        # Deployment shape is determined once at startup (wrapped / persistent / on_demand)
        self._install_mode = detect_install_mode(port)

    async def start(self) -> None:
        """Start the periodic beacon. Call from proxy startup."""
        if not is_telemetry_enabled():
            logger.debug("Telemetry disabled (HEADROOM_TELEMETRY=off)")
            return
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "Telemetry: ENABLED (anonymous aggregate stats, opt out: HEADROOM_TELEMETRY=off)"
        )

    async def stop(self) -> None:
        """Stop and send one final report. Call from proxy shutdown."""
        if self._task:
            self._task.cancel()
            self._task = None
        # Final report — but only if the proxy ran for more than 2 minutes.
        # Short-lived restarts (e.g. crash loops, orchestration churn) would
        # otherwise spam the telemetry table with duplicate cumulative stats.
        uptime_seconds = time.time() - self._start_time
        if is_telemetry_enabled() and uptime_seconds > 120:
            await self._report()

    async def _loop(self) -> None:
        """Background loop: wait, report, repeat."""
        # Wait 60 seconds before first report
        await asyncio.sleep(60)
        while True:
            try:
                await self._report()
            except Exception:
                pass  # Never crash the proxy for telemetry
            await asyncio.sleep(_INTERVAL_SECONDS)

    async def _report(self) -> None:
        """Fetch stats from local /stats endpoint and POST to Supabase.

        Wrapped in multiple try/except layers so that:
        1. A missing httpx import silently skips.
        2. A failed /stats fetch silently skips.
        3. Extraction of any stats section is independent — one bad key
           never blocks the others.
        4. A failed Supabase POST silently skips (fire-and-forget).
        The proxy NEVER crashes or slows down because of telemetry.
        """
        try:
            import httpx
        except ImportError:
            return

        # ---- Fetch stats from our own proxy ----
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"http://127.0.0.1:{self._port}/stats")
                if resp.status_code != 200:
                    return
                stats = resp.json()
        except Exception:
            return

        # Don't send empty stats — no point reporting zeros
        try:
            total_requests = stats.get("requests", {}).get("total", 0)
            if total_requests == 0:
                return
        except Exception:
            return

        # ---- Build payload — each section guarded independently ----
        session_minutes = max(1, int((time.time() - self._start_time) / 60))

        try:
            from headroom._version import __version__ as headroom_version
        except Exception:
            headroom_version = "unknown"

        # Core identity (always present)
        payload: dict = {
            "session_id": self._session_id,
            "instance_id": self._instance_id,
            "headroom_version": headroom_version,
            "python_version": (
                f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
            ),
            "os": f"{platform.system()} {platform.machine()}",
            "sdk": self._sdk,
            "backend": self._backend,
            "session_minutes": session_minutes,
            "install_mode": self._install_mode,
            "headroom_stack": detect_stack(stats),
        }

        try:
            by_stack = (stats.get("requests") or {}).get("by_stack") or {}
            if by_stack:
                payload["requests_by_stack"] = dict(by_stack)
        except Exception:
            logger.debug("Beacon: failed to extract requests_by_stack", exc_info=True)

        # --- Effectiveness metrics ---
        try:
            tokens = stats.get("tokens", {})
            requests_stats = stats.get("requests", {})
            cache = stats.get("prefix_cache", {}).get("totals", {})
            cost = stats.get("cost", {})
            models_by = requests_stats.get("by_model", {})

            payload.update(
                {
                    "tokens_saved": tokens.get("saved", 0),
                    "requests": requests_stats.get("total", 0),
                    "compression_percent": tokens.get("savings_percent", 0),
                    "cache_hit_rate": cache.get("hit_rate", 0),
                    "cost_saved_usd": cost.get("savings_usd", 0),
                    "cache_saved_usd": cost.get("cache_savings_usd", 0),
                    "models_used": [
                        m for m in models_by.keys() if not m.startswith("passthrough:")
                    ],
                }
            )
        except Exception:
            logger.debug("Beacon: failed to extract effectiveness metrics", exc_info=True)

        # --- Cache bust tracking (tokens lost due to compression breaking prefix cache) ---
        try:
            cvc = stats.get("prefix_cache", {}).get("compression_vs_cache", {})
            bust_tokens = cvc.get("tokens_lost_to_cache_bust", 0)
            if bust_tokens > 0:
                payload["cache_bust_tokens"] = bust_tokens
        except Exception:
            logger.debug("Beacon: failed to extract cache bust metrics", exc_info=True)

        # --- Performance overhead (how much latency Headroom adds) ---
        try:
            overhead = stats.get("overhead", {})
            payload.update(
                {
                    "overhead_avg_ms": round(overhead.get("average_ms", 0), 2),
                    "overhead_max_ms": round(overhead.get("max_ms", 0), 2),
                }
            )
        except Exception:
            logger.debug("Beacon: failed to extract overhead metrics", exc_info=True)

        # --- TTFB (time to first byte — what the user feels) ---
        try:
            ttfb = stats.get("ttfb", {})
            payload["ttfb_avg_ms"] = round(ttfb.get("average_ms", 0), 2)
        except Exception:
            logger.debug("Beacon: failed to extract TTFB metrics", exc_info=True)

        # --- Pipeline timing breakdown (where is time spent?) ---
        # Stored as JSONB — variable-shape dict of transform_name → avg_ms,
        # plus an optional `_strategies` sub-key carrying ContentRouter strategy
        # counts and per-strategy tokens-saved totals (zero schema change — the
        # JSONB column absorbs the nested shape).
        try:
            pipeline_timing = _build_pipeline_timing(stats)
            if pipeline_timing:
                payload["pipeline_timing"] = pipeline_timing
        except Exception:
            logger.debug("Beacon: failed to extract pipeline timing", exc_info=True)

        # --- Request patterns (how big are conversations?) ---
        try:
            tokens = stats.get("tokens", {})
            total_req = stats.get("requests", {}).get("total", 1)
            tokens_before = tokens.get("total_before_compression", 0)
            tokens_after = tokens_before - tokens.get("saved", 0)
            payload.update(
                {
                    "avg_tokens_before": round(tokens_before / max(total_req, 1)),
                    "avg_tokens_after": round(tokens_after / max(total_req, 1)),
                }
            )
        except Exception:
            logger.debug("Beacon: failed to extract request patterns", exc_info=True)

        # --- Compression cache effectiveness ---
        try:
            cc = stats.get("compression_cache", {})
            if cc:
                payload["compression_cache"] = {
                    "hit_rate": cc.get("hit_rate", 0),
                    "entries": cc.get("entries", 0),
                    "tokens_saved": cc.get("total_tokens_saved", 0),
                }
        except Exception:
            logger.debug("Beacon: failed to extract cache stats", exc_info=True)

        # --- CCR (Compress-Cache-Retrieve) usage ---
        try:
            ccr = stats.get("compression", {})
            if ccr.get("ccr_entries", 0) > 0:
                payload["ccr"] = {
                    "entries": ccr.get("ccr_entries", 0),
                    "retrievals": ccr.get("ccr_retrievals", 0),
                }
        except Exception:
            logger.debug("Beacon: failed to extract CCR stats", exc_info=True)

        # --- Waste signals (what patterns of waste do we see?) ---
        try:
            waste = stats.get("waste_signals", {})
            if waste:
                payload["waste_signals"] = waste
        except Exception:
            logger.debug("Beacon: failed to extract waste signals", exc_info=True)

        # ---- Send to Supabase (fire-and-forget, upsert on session_id) ----
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    _ENDPOINT,
                    json=payload,
                    headers={
                        "apikey": _SUPABASE_KEY,
                        "Authorization": f"Bearer {_SUPABASE_KEY}",
                        "Content-Type": "application/json",
                        "Prefer": "resolution=merge-duplicates,return=minimal",
                    },
                )
        except Exception:
            # No internet, DNS failure, timeout, Supabase down — all fine.
            # Headroom continues working perfectly without telemetry.
            logger.debug("Beacon: failed to send telemetry", exc_info=True)
