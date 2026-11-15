"""Which credential a background usage poller may use (VAPT 01-F16).

Usage pollers (the Claude subscription tracker, the Codex ``/wham/usage``
refresher) call a provider on the proxy's behalf and show the result on the
operator's dashboard. The account they poll must be the **operator's**, so a
credential *learned from traffic* is adopted only from the **local operator**: a
loopback peer whose request was not forwarded by another hop. On a shared proxy (several principals behind one Headroom), a network caller's
``Authorization`` bearer must never become the polled account — that would spend
the caller's credential on a request they never made and publish their usage on
someone else's dashboard. Without a learned token the pollers fall back to the
operator-configured credential (``CLAUDE_CODE_OAUTH_TOKEN`` or the proxy user's
own Claude Code credentials file), as before.

This keeps the single-developer experience: Claude Code on the same machine,
where the OAuth token often lives in the OS keychain rather than a file, still
gets its subscription window without extra setup.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import time
from collections.abc import Mapping
from typing import Any

from headroom.proxy.loopback_guard import is_loopback_host

# Any of these means the request crossed another hop (a gateway or reverse
# proxy on the same host), so the loopback peer is not the end caller. The
# whole ``X-Forwarded-*`` family counts (``-For``, ``-Proto``, ``-Host``, and
# any added later), so a gateway that sends only one of them still fails closed.
_FORWARDING_HEADERS = frozenset({"forwarded", "x-real-ip"})
_FORWARDING_HEADER_PREFIX = "x-forwarded-"

CODEX_QUOTA_OPERATOR_ENV = "HEADROOM_CODEX_QUOTA_OPERATOR"


def codex_operator_fingerprint(headers: Mapping[str, str]) -> str | None:
    """Stable issuer/user/workspace selector, never an authentication decision.

    The usage API still validates the bearer. Forged JWT claims cannot produce
    a quota snapshot without OpenAI accepting the token for that workspace.
    Pinning both user and workspace excludes other members of a shared account.
    """
    from headroom.providers.codex.runtime import decode_openai_bearer_payload

    lower = {key.lower(): value for key, value in headers.items()}
    payload = decode_openai_bearer_payload(lower)
    if payload is None:
        return None
    auth = payload.get("https://api.openai.com/auth")
    if not isinstance(auth, dict):
        return None
    identity = [payload.get("iss"), payload.get("sub"), auth.get("chatgpt_account_id")]
    if not all(isinstance(value, str) and value for value in identity):
        return None
    expires = payload.get("exp")
    if not isinstance(expires, (int, float)):
        return None
    try:
        if not math.isfinite(expires) or expires <= time.time():
            return None
    except OverflowError:
        return None
    requested_account = lower.get("chatgpt-account-id")
    if requested_account is not None and requested_account != identity[2]:
        return None
    return hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()


def is_configured_codex_operator(headers: Mapping[str, str]) -> bool:
    """Whether the operator explicitly selected this user/workspace for quota reads."""
    expected = os.environ.get(CODEX_QUOTA_OPERATOR_ENV, "").strip().lower()
    actual = codex_operator_fingerprint(headers) if expected else None
    return actual is not None and hmac.compare_digest(actual, expected)


def is_local_operator_connection(conn: Any) -> bool:
    """True only for a direct loopback caller (HTTP request or WebSocket).

    Fails closed: a missing peer address, a non-loopback peer, or any
    forwarding header returns ``False``. Trusted-gateway CIDRs deliberately do
    not count — a gateway fronts other principals by definition.
    """
    client = getattr(conn, "client", None)
    host = getattr(client, "host", None) if client is not None else None
    if not isinstance(host, str) or not is_loopback_host(host):
        return False
    headers = getattr(conn, "headers", None)
    if headers is not None:
        try:
            for name in headers.keys():
                name = name.lower()
                if name in _FORWARDING_HEADERS or name.startswith(_FORWARDING_HEADER_PREFIX):
                    return False
        except Exception:
            return False
    return True


if __name__ == "__main__":
    # Print only the non-secret identity selector, never access/refresh tokens.
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="Print the current Codex quota operator fingerprint"
    )
    parser.add_argument(
        "--codex-auth",
        type=Path,
        default=Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "auth.json",
    )
    args = parser.parse_args()
    try:
        tokens = json.loads(args.codex_auth.read_text())["tokens"]
        headers = {"Authorization": "Bearer " + tokens["access_token"]}
        if tokens.get("account_id"):
            headers["ChatGPT-Account-Id"] = tokens["account_id"]
        fingerprint = codex_operator_fingerprint(headers)
    except (OSError, ValueError, KeyError, TypeError):
        fingerprint = None
    if fingerprint is None:
        parser.error("No current Codex subscription identity; sign in with Codex first.")
    print(fingerprint)
