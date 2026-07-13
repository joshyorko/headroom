"""Per-request project attribution for the proxy.

``headroom wrap`` launches agents with an ``X-Headroom-Project`` header
(via ``ANTHROPIC_CUSTOM_HEADERS`` for Claude Code and ``env_http_headers``
for Codex) naming the project directory the agent is working in. The proxy
captures that header once per request — in the HTTP middleware for regular
requests and at the WebSocket accept for Codex responses-WS sessions —
into a :mod:`contextvars` variable, so the outcome funnel can attribute
savings to a project without threading a parameter through every handler.

The value is sanitized (printable characters only, length-capped) before it
is stored; an absent or unusable header simply leaves attribution off for
that request, matching pre-feature behavior.
"""

from __future__ import annotations

import base64
from collections.abc import Iterable, Mapping, MutableMapping
from contextvars import ContextVar
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from headroom.copilot_auth import is_copilot_api_url
from headroom.proxy.project_policy import (
    PROJECT_HEADER,
    PROJECT_PATH_PREFIX,
    classify_project,
    split_project_path,
    with_project_prefix,
)
from headroom.proxy.request_scope import normalize_scope_path
from headroom.proxy.savings_tracker import sanitize_project_name

CLIENT_PATH_PREFIX = "/c/"
COPILOT_UPSTREAM_PATH_PREFIX = "/_copilot/"
_PROJECT_PAYLOAD_KEYS = {
    "cwd",
    "current_dir",
    "current_directory",
    "project",
    "project_name",
    "workspace",
    "workspace_root",
    "workspace_roots",
    "working_dir",
    "working_directory",
}

_current_project: ContextVar[str | None] = ContextVar("headroom_current_project", default=None)
_current_copilot_api_url: ContextVar[str | None] = ContextVar(
    "headroom_current_copilot_api_url", default=None
)


def sanitize_client_name(value: Any) -> str | None:
    """Return a conservative client key suitable for Headroom telemetry tags."""
    if not isinstance(value, str):
        return None
    candidate = unquote(value).strip().lower().replace(" ", "-").replace("_", "-")
    if not candidate:
        return None
    sanitized = "".join(ch for ch in candidate if ch.isalnum() or ch in {"-", ".", ":"}).strip(
        "-.:"
    )
    return sanitized[:64] or None


def _encode_copilot_api_url(api_url: str) -> str:
    return base64.urlsafe_b64encode(api_url.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_copilot_api_url(value: str) -> str | None:
    try:
        padded = value + ("=" * (-len(value) % 4))
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except Exception:
        return None


def _project_name_from_value(value: Any) -> str | None:
    if isinstance(value, str):
        candidate = value.strip()
        if "/" in candidate or "\\" in candidate:
            candidate = candidate.rstrip("/\\").replace("\\", "/").rsplit("/", 1)[-1]
        return sanitize_project_name(candidate)

    if isinstance(value, Mapping):
        for key in ("name", "project", "project_name", "cwd", "path", "root"):
            project = _project_name_from_value(value.get(key))
            if project:
                return project

    if isinstance(value, Iterable) and not isinstance(value, bytes | bytearray | str):
        for item in value:
            project = _project_name_from_value(item)
            if project:
                return project

    return None


def classify_project_from_payload(payload: Any, *, _depth: int = 0) -> str | None:
    """Infer project from Codex/OpenAI request payload metadata when present."""

    if _depth > 5:
        return None

    if isinstance(payload, Mapping):
        for key, value in payload.items():
            if str(key).lower() in _PROJECT_PAYLOAD_KEYS:
                project = _project_name_from_value(value)
                if project:
                    return project

        for value in payload.values():
            project = classify_project_from_payload(value, _depth=_depth + 1)
            if project:
                return project

    if isinstance(payload, Iterable) and not isinstance(payload, bytes | bytearray | str):
        for item in payload:
            project = classify_project_from_payload(item, _depth=_depth + 1)
            if project:
                return project

    return None


def set_current_project(project: str | None) -> None:
    """Bind the active request's project for downstream outcome recording."""
    _current_project.set(sanitize_project_name(project))


def get_current_project() -> str | None:
    """Project bound to the current request context, or ``None``."""
    return _current_project.get()


def set_current_copilot_api_url(api_url: str | None) -> None:
    """Bind the active request's Copilot upstream API URL, if safely recognized."""
    candidate = api_url.strip().rstrip("/") if isinstance(api_url, str) else None
    _current_copilot_api_url.set(candidate if is_copilot_api_url(candidate) else None)


def get_current_copilot_api_url() -> str | None:
    """Copilot upstream API URL bound to the current request context, or ``None``."""
    return _current_copilot_api_url.get()


def split_client_path(path: str) -> tuple[str | None, str]:
    """Split ``/c/<client>/rest`` into ``(client, /rest)``."""
    if not path.startswith(CLIENT_PATH_PREFIX):
        return None, path
    remainder = path[len(CLIENT_PATH_PREFIX) :]
    segment, sep, rest = remainder.partition("/")
    client = sanitize_client_name(segment) if segment else None
    if client is None:
        return None, path
    return client, ("/" + rest) if sep else "/"


def split_copilot_upstream_path(path: str) -> tuple[str | None, str]:
    """Split ``/_copilot/<api-url>/rest`` into ``(api_url, /rest)``."""
    if not path.startswith(COPILOT_UPSTREAM_PATH_PREFIX):
        return None, path
    remainder = path[len(COPILOT_UPSTREAM_PATH_PREFIX) :]
    segment, sep, rest = remainder.partition("/")
    api_url = (_decode_copilot_api_url(segment) or "").strip().rstrip("/") if segment else ""
    if not api_url or not is_copilot_api_url(api_url):
        return None, path
    return api_url, ("/" + rest) if sep else "/"


def strip_project_path_prefix(scope: MutableMapping[str, Any]) -> str | None:
    """Strip a ``/p/<name>`` prefix from an ASGI scope, returning the name.

    Mutates ``scope["path"]`` (and ``raw_path``) so routing sees the
    canonical path. Must run before anything caches the request URL.
    """
    project, stripped = split_project_path(scope.get("path", ""))
    if project is not None:
        normalize_scope_path(scope, stripped)
    return project


def strip_client_path_prefix(scope: MutableMapping[str, Any]) -> str | None:
    """Strip a ``/c/<client>`` prefix from an ASGI scope, returning the client."""
    client, stripped = split_client_path(scope.get("path", ""))
    if client is not None:
        normalize_scope_path(scope, stripped)
    return client


def strip_copilot_upstream_path_prefix(scope: MutableMapping[str, Any]) -> str | None:
    """Strip a Copilot upstream prefix from an ASGI scope, returning the API URL."""
    api_url, stripped = split_copilot_upstream_path(scope.get("path", ""))
    if api_url is not None:
        normalize_scope_path(scope, stripped)
    return api_url


def with_client_prefix(base_url: str, client: str | None) -> str:
    """Insert ``/c/<client>`` ahead of a proxy base URL path."""
    name = sanitize_client_name(client)
    if name is None:
        return base_url
    parts = urlsplit(base_url)
    prefixed = f"{CLIENT_PATH_PREFIX}{quote(name, safe='')}{parts.path}"
    return urlunsplit(parts._replace(path=prefixed.rstrip("/")))


def with_copilot_upstream_prefix(base_url: str, api_url: str | None) -> str:
    """Insert a safe Copilot upstream selector ahead of the base URL path."""
    candidate = api_url.strip().rstrip("/") if isinstance(api_url, str) else None
    if not candidate or not is_copilot_api_url(candidate):
        return base_url
    parts = urlsplit(base_url)
    prefixed = f"{COPILOT_UPSTREAM_PATH_PREFIX}{_encode_copilot_api_url(candidate)}{parts.path}"
    return urlunsplit(parts._replace(path=prefixed.rstrip("/")))


__all__ = [
    "CLIENT_PATH_PREFIX",
    "COPILOT_UPSTREAM_PATH_PREFIX",
    "PROJECT_HEADER",
    "PROJECT_PATH_PREFIX",
    "classify_project",
    "classify_project_from_payload",
    "get_current_copilot_api_url",
    "get_current_project",
    "set_current_copilot_api_url",
    "set_current_project",
    "sanitize_client_name",
    "split_client_path",
    "split_copilot_upstream_path",
    "split_project_path",
    "strip_client_path_prefix",
    "strip_copilot_upstream_path_prefix",
    "strip_project_path_prefix",
    "with_client_prefix",
    "with_copilot_upstream_prefix",
    "with_project_prefix",
]
