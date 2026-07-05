"""Durable agent initialization commands."""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from hashlib import sha1
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import click

from headroom._subprocess import run

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib  # type: ignore[no-redef]

from headroom.install.models import ConfigScope, InstallPreset, RuntimeKind, SupervisorKind
from headroom.install.paths import claude_settings_path, codex_config_path, validate_profile_name
from headroom.install.planner import build_manifest
from headroom.install.providers import _apply_unix_env_scope, _apply_windows_env_scope
from headroom.install.runtime import (
    acquire_runtime_start_lock,
    resolve_headroom_command,
    resolve_headroom_config_command,
    runtime_status,
    start_detached_agent,
    start_persistent_docker,
    stop_runtime,
    wait_ready,
)
from headroom.install.state import load_manifest, save_manifest
from headroom.install.supervisors import start_supervisor
from headroom.providers.claude import TOOL_SEARCH_DEFAULT, TOOL_SEARCH_ENV
from headroom.providers.codex.install import codex_uses_chatgpt_auth
from headroom.providers.codex.threads import retag_to_headroom
from headroom.proxy.project_context import with_client_prefix

from .main import main

logger = logging.getLogger(__name__)

_VERBOSE_HANDLER_ATTR = "_headroom_init_verbose_handler"

_GLOBAL_PROFILE = "init-user"
_CLAUDE_HOOK_MARKER = "headroom-init-claude"
_COPILOT_HOOK_MARKER = "headroom-init-copilot"
_CODEX_HOOK_MARKER = "headroom-init-codex"
_CODEX_RTK_REPORT_MARKER = "headroom-init-codex-rtk-report"
_CODEX_PROVIDER_MARKER_START = "# --- Headroom Codex provider ---"
_CODEX_PROVIDER_MARKER_END = "# --- end Headroom Codex provider ---"
_LEGACY_CODEX_PROVIDER_MARKERS = (
    ("# --- Headroom init provider ---", "# --- end Headroom init provider ---"),
    ("# --- Headroom proxy (auto-injected by headroom wrap codex) ---", "# --- end Headroom ---"),
)
_CODEX_FEATURE_MARKER_START = "# --- Headroom init features ---"
_CODEX_FEATURE_MARKER_END = "# --- end Headroom init features ---"
_PROJECT_HEADER_NAME = "X-Headroom-Project"
_SUPPORTED_TARGETS = ("claude", "copilot", "codex", "openclaw")
_LOCAL_TARGETS = {"claude", "codex"}
_GLOBAL_TARGETS = {"claude", "copilot", "codex", "openclaw"}
_STARTUP_READY_TIMEOUT_SECONDS = 15
_TOML_TABLE_HEADER_RE = re.compile(r"^[ \t]*(?:\[\[[^\]\r\n]+\]\]|\[[^\]\r\n]+\])[ \t]*(?:#.*)?$")
_TOML_FEATURES_NAME_RE = r"(?:features|\"features\"|'features')"
_TOML_CODEX_HOOKS_NAME_RE = r"(?:codex_hooks|\"codex_hooks\"|'codex_hooks')"
_CODEX_FEATURES_TABLE_RE = re.compile(
    rf"^[ \t]*\[[ \t]*{_TOML_FEATURES_NAME_RE}[ \t]*\][ \t]*(?:#.*)?$"
)
_CODEX_FEATURES_DOTTED_LEGACY_RE = re.compile(
    rf"^[ \t]*{_TOML_FEATURES_NAME_RE}[ \t]*\.[ \t]*{_TOML_CODEX_HOOKS_NAME_RE}[ \t]*="
)
_CODEX_FEATURES_LEGACY_KEY_RE = re.compile(rf"^[ \t]*{_TOML_CODEX_HOOKS_NAME_RE}[ \t]*=")


def _command_string(parts: list[str]) -> str:
    if os.name == "nt":
        # Normalize backslash paths to forward slashes so hook commands
        # work when Claude Code executes them via Git Bash (#724).
        parts = [p.replace("\\", "/") for p in parts]
        return subprocess.list2cmdline(parts)
    return shlex.join(parts)


def _hook_command(*parts: str) -> str:
    return _command_string([*resolve_headroom_config_command(), "init", "hook", "ensure", *parts])


def _codex_rtk_report_command(proxy_url: str) -> str:
    command = _command_string(
        [
            *resolve_headroom_config_command(),
            "mcp",
            "report-rtk",
            "--proxy-url",
            proxy_url,
            "--scope",
            "project",
        ]
    )
    return f"{command} >/dev/null 2>&1 || true # {_CODEX_RTK_REPORT_MARKER}"


def _powershell_matcher() -> str:
    return "Bash|PowerShell" if os.name == "nt" else "Bash"


def _enable_verbose_logging() -> None:
    """Attach a stderr handler to the init logger at DEBUG level.

    Idempotent: calling this multiple times in one process (e.g. when nested
    subcommands are invoked) leaves exactly one handler attached. Does NOT
    mutate stdout; all verbose output goes to stderr so ``headroom init``
    can still be composed in pipes that consume stdout.
    """

    if getattr(logger, _VERBOSE_HANDLER_ATTR, None) is not None:
        return
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter("[headroom init] %(message)s"))
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    setattr(logger, _VERBOSE_HANDLER_ATTR, handler)


def _local_profile(cwd: Path | None = None) -> str:
    root = (cwd or Path.cwd()).resolve()
    slug = "".join(ch if ch.isalnum() or ch in "-._" else "-" for ch in root.name.lower()).strip(
        "-"
    )
    digest = sha1(str(root).encode("utf-8")).hexdigest()[:8]
    return validate_profile_name(f"init-{slug or 'repo'}-{digest}")


def _local_project_name(cwd: Path | None = None) -> str:
    root = (cwd or Path.cwd()).resolve()
    return root.name.strip() or "project"


def _normalize_proxy_url(proxy_url: str | None, port: int) -> str:
    return (proxy_url or f"http://127.0.0.1:{port}").rstrip("/")


def _proxy_url_uses_local_runtime(proxy_url: str) -> bool:
    host = (urlsplit(proxy_url.rstrip("/")).hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"}


def _proxy_v1_url(proxy_url: str) -> str:
    url = proxy_url.rstrip("/")
    return url if url.endswith("/v1") else f"{url}/v1"


def _proxy_project_v1_url(proxy_url: str, project: str) -> str:
    parts = urlsplit(proxy_url.rstrip("/"))
    path = parts.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[: -len("/v1")].rstrip("/")
    path = f"{path}/p/{quote(project, safe='')}/v1"
    return urlunsplit(parts._replace(path=path))


def _toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _runtime_profile(global_scope: bool, cwd: Path | None = None) -> str:
    return _GLOBAL_PROFILE if global_scope else _local_profile(cwd)


def _copilot_config_path() -> Path:
    return Path.home() / ".copilot" / "config.json"


def _codex_hooks_path(global_scope: bool) -> Path:
    return (Path.home() if global_scope else Path.cwd()) / ".codex" / "hooks.json"


def _claude_scope_path(global_scope: bool) -> Path:
    if global_scope:
        return claude_settings_path()
    return Path.cwd() / ".claude" / "settings.local.json"


def _codex_scope_path(global_scope: bool) -> Path:
    if global_scope:
        return codex_config_path()
    return Path.cwd() / ".codex" / "config.toml"


def _json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return {}
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        content = _strip_json_comments(content).strip()
        if not content:
            return {}
        payload = json.loads(content)
    return payload if isinstance(payload, dict) else {}


def _strip_json_comments(content: str) -> str:
    """Strip JSONC-style comments while preserving string contents."""
    result: list[str] = []
    in_string = False
    escaped = False
    i = 0
    while i < len(content):
        char = content[i]
        next_char = content[i + 1] if i + 1 < len(content) else ""

        if in_string:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            i += 1
            continue

        if char == '"':
            in_string = True
            result.append(char)
            i += 1
            continue

        if char == "/" and next_char == "/":
            i += 2
            while i < len(content) and content[i] not in "\r\n":
                i += 1
            continue

        if char == "/" and next_char == "*":
            i += 2
            while i + 1 < len(content) and not (content[i] == "*" and content[i + 1] == "/"):
                result.append("\n" if content[i] in "\r\n" else " ")
                i += 1
            i += 2 if i + 1 < len(content) else 0
            continue

        result.append(char)
        i += 1
    return "".join(result)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    logger.debug("write json: %s (keys=%s)", path, sorted(payload.keys()))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _ensure_claude_hooks(path: Path, profile: str, port: int) -> None:
    logger.debug("ensure claude hooks: %s (profile=%s, port=%s)", path, profile, port)
    payload = _json_file(path)
    env_map = dict(payload.get("env") or {}) if isinstance(payload.get("env"), dict) else {}
    env_map["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{port}"
    # GH #746: with a custom ANTHROPIC_BASE_URL and ENABLE_TOOL_SEARCH unset,
    # Claude Code stops deferring MCP/system tool schemas and materializes them
    # all into its context window — overflowing it (breaks sub-agent spawns,
    # forces constant compaction). Keep deferral on; respect a user-set value.
    # Shares the TOOL_SEARCH_* constants with `wrap` and `install`.
    env_map.setdefault(TOOL_SEARCH_ENV, TOOL_SEARCH_DEFAULT)
    payload["env"] = env_map

    hooks = dict(payload.get("hooks") or {}) if isinstance(payload.get("hooks"), dict) else {}
    command = _hook_command("--profile", profile)
    for event, matcher in (
        ("SessionStart", "startup|resume"),
        ("PreToolUse", _powershell_matcher()),
    ):
        entries = list(hooks.get(event) or []) if isinstance(hooks.get(event), list) else []
        retained: list[dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                retained.append(entry)
                continue
            hook_items = entry.get("hooks")
            if not isinstance(hook_items, list):
                retained.append(entry)
                continue
            has_headroom = any(
                isinstance(item, dict)
                and item.get("command")
                and _CLAUDE_HOOK_MARKER in str(item.get("command"))
                for item in hook_items
            )
            if not has_headroom:
                retained.append(entry)
        retained.append(
            {
                "matcher": matcher,
                "hooks": [
                    {
                        "type": "command",
                        "command": f"{command} --marker {_CLAUDE_HOOK_MARKER}",
                        "timeout": 15,
                    }
                ],
            }
        )
        hooks[event] = retained
    payload["hooks"] = hooks
    _write_json(path, payload)


def _ensure_copilot_hooks(path: Path, profile: str) -> None:
    logger.debug("ensure copilot hooks: %s (profile=%s)", path, profile)
    payload = _json_file(path)
    hooks = dict(payload.get("hooks") or {}) if isinstance(payload.get("hooks"), dict) else {}
    command = f"{_hook_command('--profile', profile)} --marker {_COPILOT_HOOK_MARKER}"
    for event in ("SessionStart", "PreToolUse"):
        entries = list(hooks.get(event) or []) if isinstance(hooks.get(event), list) else []
        retained = [
            entry
            for entry in entries
            if not (
                isinstance(entry, dict) and _COPILOT_HOOK_MARKER in str(entry.get("command", ""))
            )
        ]
        retained.append({"type": "command", "command": command, "cwd": ".", "timeout": 15})
        hooks[event] = retained
    payload["hooks"] = hooks
    _write_json(path, payload)


def _replace_marker_block(
    content: str, marker_start: str, marker_end: str, block: str, *, at_root: bool = False
) -> str:
    content = _remove_marker_block(content, marker_start, marker_end)
    block = block.strip()
    if at_root:
        # The block carries top-level keys, so it must sit above the first table
        # header; appended after a table (e.g. [features]) TOML scopes those keys
        # into that table and Codex rejects the config (#260).
        lines = content.splitlines()
        for index, line in enumerate(lines):
            if _TOML_TABLE_HEADER_RE.search(line):
                head = "\n".join(lines[:index]).rstrip()
                tail = "\n".join(lines[index:]).lstrip("\n")
                prefix = f"{head}\n\n" if head else ""
                return (f"{prefix}{block}\n\n{tail}").rstrip() + "\n"
    return (content.rstrip() + "\n\n" + block + "\n").lstrip()


def _remove_marker_block(content: str, marker_start: str, marker_end: str) -> str:
    if marker_start not in content or marker_end not in content:
        return content
    start = content.index(marker_start)
    end = content.index(marker_end) + len(marker_end)
    return content[:start].rstrip() + "\n\n" + content[end:].lstrip()


def _strip_codex_provider_marker_spans(content: str) -> str:
    for marker_start, marker_end in (
        (_CODEX_PROVIDER_MARKER_START, _CODEX_PROVIDER_MARKER_END),
        *_LEGACY_CODEX_PROVIDER_MARKERS,
    ):
        while marker_start in content and marker_end in content:
            start = content.index(marker_start)
            end_idx = content.index(marker_end, start)
            if end_idx < start:
                break
            end = end_idx + len(marker_end)
            content = content[:start].rstrip("\n") + "\n" + content[end:].lstrip("\n")
        content = content.replace(marker_start + "\n", "")
        content = content.replace(marker_end + "\n", "")
    return content


def _strip_codex_init_block(content: str) -> str:
    """Remove all Headroom init-managed blocks and orphan keys from a Codex config.toml string."""
    import re

    content = _strip_codex_provider_marker_spans(content)

    # Strip any orphan top-level keys that a crashed or partial write may have
    # left outside the marker block. Only remove openai_base_url when the same
    # file still carries Headroom's model/provider marker, so uninstall-style
    # cleanup does not erase an unrelated user-managed provider URL.
    has_orphan_headroom_provider = bool(
        re.search(r'(?m)^[ \t]*model_provider[ \t]*=[ \t]*"headroom"[ \t]*\r?$', content)
        or re.search(
            r'(?m)^[ \t]*name[ \t]*=[ \t]*"(?:Headroom init proxy|OpenAI via Headroom proxy)"[ \t]*\r?$',
            content,
        )
        or re.search(rf'(?m)^[ \t]*env_http_headers[ \t]*=.*"{_PROJECT_HEADER_NAME}"', content)
    )
    content = re.sub(r'(?m)^[ \t]*model_provider[ \t]*=[ \t]*"headroom"[ \t]*\r?\n', "", content)
    if has_orphan_headroom_provider:
        content = re.sub(r"(?m)^[ \t]*openai_base_url[ \t]*=.*\r?\n", "", content)

    # Strip any orphaned [model_providers.headroom] table that is recognisably ours.
    orphan_headroom_table = re.compile(
        r"(?ms)^\[model_providers\.headroom\][^\[]*?"
        r"("
        r'name[ \t]*=[ \t]*"(?:Headroom init proxy|OpenAI via Headroom proxy)"'
        r"|"
        rf'env_http_headers[ \t]*=.*"{_PROJECT_HEADER_NAME}"'
        r")"
        r"[^\[]*?"
        r"(?=^\[|\Z)"
    )
    content = orphan_headroom_table.sub("", content)

    return content.lstrip("\n").rstrip() + "\n" if content.strip() else ""


def _strip_all_codex_headroom_provider_tables(content: str) -> str:
    """Remove every Headroom-managed Codex provider table before reinserting one."""

    content = _strip_codex_provider_marker_spans(content)

    # Also scrub unmarked blocks that this command owns. The name check keeps
    # user-managed provider tables intact.
    owned_table = re.compile(
        r"(?ms)^\[model_providers\.headroom\]\r?\n"
        r"(?:(?!^\[).)*?"
        r'^[ \t]*name[ \t]*=[ \t]*"(?:Headroom (?:init )?proxy|OpenAI via Headroom proxy)"[ \t]*\r?\n'
        r"(?:(?!^\[).)*?(?=^\[|\Z)"
    )
    content = owned_table.sub("", content)
    return content.lstrip("\n").rstrip() + "\n"


def _codex_provider_matches(content: str, provider_url: str, *, requires_openai_auth: bool) -> bool:
    if not content.strip():
        return False
    try:
        parsed = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return False

    provider = parsed.get("model_providers", {}).get("headroom")
    if not isinstance(provider, dict):
        return False
    headers = provider.get("env_http_headers")
    if not isinstance(headers, dict):
        return False

    if parsed.get("model_provider") != "headroom":
        return False
    if parsed.get("openai_base_url") != provider_url:
        return False
    if provider.get("name") != "OpenAI via Headroom proxy":
        return False
    if provider.get("base_url") != provider_url:
        return False
    if provider.get("supports_websockets") is not True:
        return False
    if headers.get(_PROJECT_HEADER_NAME) != "HEADROOM_PROJECT":
        return False
    if requires_openai_auth:
        return provider.get("requires_openai_auth") is True
    return provider.get("requires_openai_auth") is not True


def _ensure_codex_provider(path: Path, provider_url: str | int) -> None:
    import re

    if isinstance(provider_url, int):
        provider_url = _proxy_v1_url(_normalize_proxy_url(None, provider_url))

    logger.debug("ensure codex provider block: %s (provider_url=%s)", path, provider_url)
    # Emit requires_openai_auth only for ChatGPT-OAuth users (restores the
    # account menu); omitting it for API-key users avoids forcing an OAuth
    # login (#406).
    uses_chatgpt_auth = codex_uses_chatgpt_auth(path.parent / "auth.json")
    requires_openai_auth = "requires_openai_auth = true\n" if uses_chatgpt_auth else ""
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    if _codex_provider_matches(content, provider_url, requires_openai_auth=uses_chatgpt_auth):
        retag_to_headroom(path.parent)
        return
    block = (
        f"{_CODEX_PROVIDER_MARKER_START}\n"
        'model_provider = "headroom"\n'
        f"openai_base_url = {_toml_string(provider_url)}\n\n"
        "[model_providers.headroom]\n"
        'name = "OpenAI via Headroom proxy"\n'
        f"base_url = {_toml_string(provider_url)}\n"
        "supports_websockets = true\n"
        f"{requires_openai_auth}"
        f'env_http_headers = {{ "{_PROJECT_HEADER_NAME}" = "HEADROOM_PROJECT" }}\n'
        f"{_CODEX_PROVIDER_MARKER_END}"
    )
    content = _strip_all_codex_headroom_provider_tables(content)
    # init owns model_provider/openai_base_url: drop any prior assignment (any
    # value, including one an older version mis-scoped under a table) so we
    # replace it instead of emitting a duplicate top-level key (#260).
    content = re.sub(r"(?m)^[ \t]*model_provider[ \t]*=.*\r?\n", "", content)
    content = re.sub(r"(?m)^[ \t]*openai_base_url[ \t]*=.*\r?\n", "", content)
    # The provider block carries top-level keys (model_provider, openai_base_url),
    # so it must land at the document root rather than after a trailing table (#260).
    content = _replace_marker_block(
        content, _CODEX_PROVIDER_MARKER_START, _CODEX_PROVIDER_MARKER_END, block, at_root=True
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    # Codex filters its history menu by the active model_provider, so existing
    # native threads vanish once we switch to "headroom". Retag them to match the
    # active provider so the history stays whole (#961), mirroring the install
    # (providers.codex.install) and wrap (cli.wrap) paths. The revert direction is
    # handled by `headroom unwrap codex`.
    retag_to_headroom(path.parent)


def _codex_feature_block() -> str:
    return f"{_CODEX_FEATURE_MARKER_START}\nhooks = true\n{_CODEX_FEATURE_MARKER_END}"


def _codex_dotted_feature_block() -> str:
    return f"{_CODEX_FEATURE_MARKER_START}\nfeatures.hooks = true\n{_CODEX_FEATURE_MARKER_END}"


def _codex_features_table_index(lines: list[str]) -> int | None:
    return next(
        (index for index, line in enumerate(lines) if _CODEX_FEATURES_TABLE_RE.search(line)),
        None,
    )


def _codex_features(content: str) -> dict[str, Any] | None:
    if not content.strip():
        return None
    try:
        parsed = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return None
    features = parsed.get("features")
    return features if isinstance(features, dict) else None


def _codex_features_has_hooks(content: str) -> bool:
    features = _codex_features(content)
    if features is None:
        # Keep init resilient for already-invalid user configs; this fallback
        # only needs to avoid adding a second obvious hooks line.
        lines = content.splitlines()
        features_index = _codex_features_table_index(lines)
        if features_index is None:
            return False
        for line in lines[features_index + 1 :]:
            if _TOML_TABLE_HEADER_RE.search(line):
                break
            if re.search(r"^[ \t]*hooks[ \t]*=", line):
                return True
        return False

    return "hooks" in features


def _strip_codex_legacy_feature_flag(content: str) -> str:
    lines = content.splitlines(keepends=True)
    retained: list[str] = []
    in_features = False
    in_root = True

    for line in lines:
        if _TOML_TABLE_HEADER_RE.search(line):
            in_root = False
            in_features = bool(_CODEX_FEATURES_TABLE_RE.search(line))
            retained.append(line)
            continue
        if (in_root and _CODEX_FEATURES_DOTTED_LEGACY_RE.search(line)) or (
            in_features and _CODEX_FEATURES_LEGACY_KEY_RE.search(line)
        ):
            continue
        retained.append(line)

    return "".join(retained)


def _ensure_codex_feature_flag(path: Path) -> None:
    """Ensure Codex's ``[features].hooks`` flag is enabled in config.toml.

    ``hooks`` is the canonical key. ``codex_hooks`` was the original key name and
    still resolves as a deprecated alias, but Codex >= 0.129 emits a deprecation
    warning for it (renamed in openai/codex#20522). Any legacy
    ``[features].codex_hooks`` line is removed, whether inside or outside our
    marker block, so a migrated config drops the deprecated key and never
    collides with a duplicate ``hooks`` key. A user-managed ``hooks`` value
    outside our marker block is left untouched.
    """
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    # Drop the deprecated alias key from [features]. Mirrors the top-level key
    # cleanup in _ensure_codex_provider (#260) so re-running init migrates a
    # legacy config rather than producing a duplicate `hooks` key, while leaving
    # unrelated user tables untouched.
    content = _strip_codex_legacy_feature_flag(content)
    if _CODEX_FEATURE_MARKER_START in content and _CODEX_FEATURE_MARKER_END in content:
        # init owns its marker block; remove it first, then reinsert under the
        # correct TOML scope below.
        content = _remove_marker_block(
            content, _CODEX_FEATURE_MARKER_START, _CODEX_FEATURE_MARKER_END
        )

    if _codex_features_has_hooks(content):
        # A user-managed `[features].hooks` key already exists outside our
        # marker block; respect their value. Clearing the legacy key above was
        # the only work.
        pass
    else:
        lines = content.splitlines()
        features_index = _codex_features_table_index(lines)
        if features_index is not None:
            # Leading blank line matches the normalisation _replace_marker_block
            # applies on later runs, so re-running init is byte-idempotent.
            lines[features_index + 1 : features_index + 1] = [
                "",
                *_codex_feature_block().splitlines(),
            ]
            content = "\n".join(lines).rstrip() + "\n"
        elif _codex_features(content) is not None:
            # The user expressed [features] via dotted keys, so adding a new
            # table would duplicate it. Keep this key at the document root.
            content = _replace_marker_block(
                content,
                _CODEX_FEATURE_MARKER_START,
                _CODEX_FEATURE_MARKER_END,
                _codex_dotted_feature_block(),
                at_root=True,
            )
        else:
            content = (
                content.rstrip() + "\n\n[features]\n\n" + _codex_feature_block() + "\n"
            ).lstrip()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _ensure_codex_hooks(path: Path, profile: str, proxy_url: str) -> None:
    logger.debug("ensure codex hooks: %s (profile=%s)", path, profile)
    ensure_command = (
        f"{_hook_command('--profile', profile)} --marker {_CODEX_HOOK_MARKER}"
        if _proxy_url_uses_local_runtime(proxy_url)
        else None
    )
    rtk_report_command = _codex_rtk_report_command(proxy_url)
    session_hooks = [
        {
            "type": "command",
            "command": rtk_report_command,
            "timeout": 15,
        }
    ]
    if ensure_command:
        session_hooks.insert(0, {"type": "command", "command": ensure_command, "timeout": 15})
    payload = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "startup|resume",
                    "hooks": session_hooks,
                }
            ],
        }
    }
    if ensure_command:
        payload["hooks"]["PreToolUse"] = [
            {
                "matcher": "Bash",
                "hooks": [{"type": "command", "command": ensure_command, "timeout": 15}],
            }
        ]
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == rendered:
        return
    path.write_text(rendered, encoding="utf-8")
    _prune_codex_hook_trust(path)


def _prune_codex_hook_trust(hooks_path: Path) -> None:
    """Drop stale Codex trust hashes for a hooks file we just rewrote.

    Codex keys hook trust by hooks.json path and event/index. If Headroom changes
    the command text from a checkout-local path to the portable ``headroom``
    executable, the old trusted hashes no longer describe the hook file. Remove
    only entries for this hooks path so Codex can re-approve the current hooks.
    """

    config_path = codex_config_path()
    if not config_path.exists():
        return
    content = config_path.read_text(encoding="utf-8")
    resolved = str(hooks_path.resolve()).replace("\\", "\\\\").replace('"', '\\"')
    pattern = re.compile(
        rf'(?ms)^\[hooks\.state\."{re.escape(resolved)}:[^"]+"\]\n'
        rf"(?:[^\n]*\n)*?"
        rf"(?=^\[|\Z)"
    )
    cleaned = pattern.sub("", content)
    if cleaned != content:
        config_path.write_text(cleaned, encoding="utf-8")


def _manifest_changed(
    existing: Any,
    *,
    port: int,
    backend: str,
    anyllm_provider: str | None,
    region: str | None,
    memory: bool,
) -> bool:
    return any(
        [
            getattr(existing, "port", port) != port,
            getattr(existing, "backend", backend) != backend,
            getattr(existing, "anyllm_provider", anyllm_provider) != anyllm_provider,
            getattr(existing, "region", region) != region,
            getattr(existing, "memory_enabled", memory) != memory,
        ]
    )


def _ensure_runtime_manifest(
    *,
    global_scope: bool,
    targets: list[str],
    port: int,
    backend: str,
    anyllm_provider: str | None,
    region: str | None,
    memory: bool,
) -> str:
    profile = _runtime_profile(global_scope)
    existing = load_manifest(profile)
    merged_targets = sorted(set(existing.targets if existing else []).union(targets))
    manifest = build_manifest(
        profile=profile,
        preset=InstallPreset.PERSISTENT_TASK.value,
        runtime_kind=RuntimeKind.PYTHON.value,
        scope=ConfigScope.USER.value,
        provider_mode="manual",
        targets=merged_targets,
        port=port,
        backend=backend,
        anyllm_provider=anyllm_provider,
        region=region,
        proxy_mode="token",
        memory_enabled=memory,
        telemetry_enabled=True,
        image="ghcr.io/chopratejas/headroom:latest",
    )
    manifest.supervisor_kind = SupervisorKind.NONE.value
    manifest.artifacts = []
    manifest.mutations = existing.mutations if existing else []
    if existing is not None and _manifest_changed(
        existing,
        port=port,
        backend=backend,
        anyllm_provider=anyllm_provider,
        region=region,
        memory=memory,
    ):
        try:
            stop_runtime(existing)
        except Exception:
            pass
    save_manifest(manifest)
    return profile


def _env_manifest(values: dict[str, str]) -> Any:
    return build_manifest(
        profile="init-env",
        preset=InstallPreset.PERSISTENT_TASK.value,
        runtime_kind=RuntimeKind.PYTHON.value,
        scope=ConfigScope.USER.value,
        provider_mode="manual",
        targets=["copilot"],
        port=8787,
        backend="anthropic",
        anyllm_provider=None,
        region=None,
        proxy_mode="token",
        memory_enabled=False,
        telemetry_enabled=True,
        image="ghcr.io/chopratejas/headroom:latest",
    )


def _apply_user_env(values: dict[str, str]) -> None:
    manifest = _env_manifest(values)
    manifest.base_env = {}
    manifest.tool_envs = {"copilot": values}
    scope = "windows" if os.name == "nt" else "unix"
    logger.debug("apply user env scope=%s keys=%s", scope, sorted(values.keys()))
    if os.name == "nt":
        _apply_windows_env_scope(manifest)
    else:
        _apply_unix_env_scope(manifest)


def _resolve_copilot_env(port: int, backend: str, proxy_url: str | None = None) -> dict[str, str]:
    root_url = _normalize_proxy_url(proxy_url, port)
    if backend == "anthropic":
        return {
            "COPILOT_PROVIDER_TYPE": "anthropic",
            "COPILOT_PROVIDER_BASE_URL": with_client_prefix(root_url, "copilot"),
        }
    return {
        "COPILOT_PROVIDER_TYPE": "openai",
        "COPILOT_PROVIDER_BASE_URL": with_client_prefix(_proxy_v1_url(root_url), "copilot"),
        "COPILOT_PROVIDER_WIRE_API": "completions",
    }


def _marketplace_source() -> str:
    override = os.environ.get("HEADROOM_MARKETPLACE_SOURCE")
    if override:
        return override
    repo_root = Path(__file__).resolve().parents[2]
    if (repo_root / ".claude-plugin" / "marketplace.json").exists():
        return str(repo_root)
    return "chopratejas/headroom"


def _run_checked(command: list[str], *, action: str) -> None:
    logger.debug("subprocess [%s]: %s", action, _command_string(command))
    result = run(
        command,
        capture_output=True,
        text=True,
    )
    logger.debug(
        "subprocess [%s] exit=%s stdout=%r stderr=%r",
        action,
        result.returncode,
        result.stdout[:200],
        result.stderr[:200],
    )
    if result.returncode == 0:
        return
    detail = "\n".join(part for part in (result.stderr.strip(), result.stdout.strip()) if part)
    if "already" in detail.lower() or "exists" in detail.lower():
        logger.debug(
            "subprocess [%s] non-zero exit tolerated ('already'/'exists' detected)", action
        )
        return
    raise click.ClickException(f"{action} failed: {detail or result.returncode}")


def _install_claude_marketplace(scope: str) -> None:
    claude_bin = shutil.which("claude")
    if not claude_bin:
        raise click.ClickException("'claude' not found in PATH. Install Claude Code first.")
    source = _marketplace_source()
    _run_checked(
        [claude_bin, "plugin", "marketplace", "add", source], action="claude marketplace add"
    )
    _run_checked(
        [claude_bin, "plugin", "install", "headroom@headroom-marketplace", "--scope", scope],
        action="claude plugin install",
    )


def _install_copilot_marketplace() -> None:
    copilot_bin = shutil.which("copilot")
    if not copilot_bin:
        raise click.ClickException("'copilot' not found in PATH. Install GitHub Copilot CLI first.")
    source = _marketplace_source()
    _run_checked(
        [copilot_bin, "plugin", "marketplace", "add", source],
        action="copilot marketplace add",
    )
    _run_checked(
        [copilot_bin, "plugin", "install", "headroom@headroom-marketplace"],
        action="copilot plugin install",
    )


@contextmanager
def _suppress_hook_output() -> Iterator[None]:
    """Keep best-effort hook recovery from emitting invalid hook output."""
    stdout_fd = os.dup(1)
    stderr_fd = os.dup(2)
    try:
        with open(os.devnull, "w", encoding="utf-8") as devnull:
            sys.stdout.flush()
            sys.stderr.flush()
            os.dup2(devnull.fileno(), 1)
            os.dup2(devnull.fileno(), 2)
            with redirect_stdout(devnull), redirect_stderr(devnull):
                yield
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(stdout_fd, 1)
        os.dup2(stderr_fd, 2)
        os.close(stdout_fd)
        os.close(stderr_fd)


def _ensure_profile_running(profile: str) -> None:
    manifest = load_manifest(profile)
    if manifest is None:
        return
    with _suppress_hook_output():
        if wait_ready(manifest, timeout_seconds=1):
            return
        try:
            with acquire_runtime_start_lock(manifest.profile) as acquired:
                if not acquired:
                    return
                if wait_ready(manifest, timeout_seconds=1):
                    return
                if runtime_status(manifest) == "running":
                    if wait_ready(manifest, timeout_seconds=_STARTUP_READY_TIMEOUT_SECONDS):
                        return
                    stop_runtime(manifest)
                if manifest.preset == InstallPreset.PERSISTENT_DOCKER.value:
                    start_persistent_docker(manifest)
                elif manifest.supervisor_kind == SupervisorKind.SERVICE.value:
                    start_supervisor(manifest)
                else:
                    start_detached_agent(manifest.profile)
                wait_ready(manifest, timeout_seconds=45)
        except Exception:
            return


def _probe_init_targets(global_scope: bool) -> list[tuple[str, str | None]]:
    """Return ``[(target, which_result)]`` for every in-scope supported target.

    ``which_result`` is the absolute path reported by :func:`shutil.which`, or
    ``None`` when the binary is not on PATH. Callers use the list both to
    build an auto-detected target list and to produce a diagnostic error
    message when nothing was found.
    """

    allowed = _GLOBAL_TARGETS if global_scope else _LOCAL_TARGETS
    logger.debug(
        "detect_init_targets: global_scope=%s allowed=%s",
        global_scope,
        sorted(allowed),
    )
    probes: list[tuple[str, str | None]] = []
    for target in _SUPPORTED_TARGETS:
        if target not in allowed:
            continue
        path = shutil.which(target)
        logger.debug("detect_init_targets: shutil.which(%r) -> %s", target, path or "None")
        probes.append((target, path))
    return probes


def detect_init_targets(global_scope: bool) -> list[str]:
    """Return agent names in scope for which a binary was found on PATH."""

    return [name for name, path in _probe_init_targets(global_scope) if path]


def _format_empty_detection_error(global_scope: bool) -> str:
    """Build the error message shown when no in-scope targets were detected.

    Lists every agent that was probed, what ``shutil.which`` returned, and
    confirms how to proceed explicitly — including that the ``-g`` / ``--global``
    flag the user tried is still valid.
    """

    probes = _probe_init_targets(global_scope)
    scope_flag = "-g" if global_scope else ""
    scope_label = "user" if global_scope else "local"

    lines: list[str] = [
        f"No supported {scope_label}-scope agents were found on PATH.",
        "",
        "Headroom probed the following agents via shutil.which():",
    ]
    for name, path in probes:
        status = f"found at {path}" if path else "not found"
        lines.append(f"  - {name}: {status}")

    lines.extend(
        [
            "",
            f"The {scope_flag or '--local (no flag)'} option is still supported; "
            "headroom init just needs to know which agent to target.",
            "Install the agent you want first, then re-run with an explicit target:",
            "",
        ]
    )
    for name, _path in probes:
        flag = " -g" if global_scope else ""
        lines.append(f"  headroom init{flag} {name}")

    lines.extend(
        [
            "",
            "Tip: run `headroom init --help` to see all options.",
        ]
    )
    return "\n".join(lines)


def _init_claude(*, global_scope: bool, profile: str, port: int) -> None:
    _ensure_claude_hooks(_claude_scope_path(global_scope), profile, port)
    _install_claude_marketplace("user" if global_scope else "local")
    click.echo(f"Configured Claude Code ({'user' if global_scope else 'local'} scope).")
    click.echo("Restart Claude Code to activate Headroom hooks and provider routing.")


def _init_copilot(
    *,
    global_scope: bool,
    profile: str,
    port: int,
    backend: str,
    proxy_url: str | None = None,
) -> None:
    if not global_scope:
        raise click.ClickException(
            "Copilot durable init currently requires -g (current-user scope)."
        )
    _ensure_copilot_hooks(_copilot_config_path(), profile)
    _apply_user_env(_resolve_copilot_env(port, backend, proxy_url=proxy_url))
    _install_copilot_marketplace()
    click.echo("Configured GitHub Copilot CLI (user scope).")
    click.echo("Restart Copilot CLI to activate Headroom hooks and provider routing.")


def _configure_codex_durable_setup(
    *,
    global_scope: bool,
    profile: str,
    port: int,
    proxy_url: str | None = None,
    install_hooks: bool = True,
    install_headroom_mcp: bool = True,
    serena: bool = False,
    no_serena: bool = False,
    no_tokensave: bool = False,
    code_graph: bool = False,
    verbose: bool = False,
) -> str:
    normalized_proxy_url = _normalize_proxy_url(proxy_url, port)
    project_config_path = _codex_scope_path(global_scope)

    if global_scope:
        _ensure_codex_provider(project_config_path, _proxy_v1_url(normalized_proxy_url))
    else:
        _ensure_codex_provider(codex_config_path(), _proxy_v1_url(normalized_proxy_url))
    if install_hooks:
        _ensure_codex_feature_flag(project_config_path)
        _ensure_codex_hooks(_codex_hooks_path(global_scope), profile, normalized_proxy_url)

    if install_headroom_mcp:
        _install_headroom_mcp_for_targets(
            targets=["codex"],
            proxy_url=normalized_proxy_url,
            force=True,
        )

    from headroom.cli import wrap as wrap_cli
    from headroom.mcp_registry import CodexRegistrar

    wrap_cli._setup_coding_compressor(
        CodexRegistrar(),
        serena_context="codex",
        serena=serena,
        no_serena=no_serena,
        no_tokensave=no_tokensave,
        verbose=verbose,
        force=True,
    )
    if code_graph:
        wrap_cli._setup_code_graph(verbose=verbose)

    return normalized_proxy_url


def _init_codex(
    *,
    global_scope: bool,
    profile: str,
    port: int,
    proxy_url: str | None = None,
    serena: bool = False,
    no_serena: bool = False,
    no_tokensave: bool = False,
    code_graph: bool = False,
    verbose: bool = False,
) -> None:
    _configure_codex_durable_setup(
        global_scope=global_scope,
        profile=profile,
        port=port,
        proxy_url=proxy_url,
        install_hooks=True,
        install_headroom_mcp=True,
        serena=serena,
        no_serena=no_serena,
        no_tokensave=no_tokensave,
        code_graph=code_graph,
        verbose=verbose,
    )
    click.echo(f"Configured Codex ({'user' if global_scope else 'local'} scope).")
    if os.name == "nt":
        click.echo(
            "Codex hooks are currently disabled upstream on Windows; provider routing was still installed."
        )
    click.echo("Restart Codex to activate Headroom configuration.")


def _init_openclaw(*, global_scope: bool, port: int) -> None:
    if not global_scope:
        raise click.ClickException(
            "OpenClaw durable init currently requires -g (current-user scope)."
        )
    command = [*resolve_headroom_command(), "wrap", "openclaw", "--proxy-port", str(port)]
    result = subprocess.run(command)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def _run_init_targets(
    *,
    targets: list[str],
    global_scope: bool,
    port: int,
    backend: str,
    anyllm_provider: str | None,
    region: str | None,
    memory: bool,
    proxy_url: str | None = None,
    serena: bool = False,
    no_serena: bool = False,
    no_tokensave: bool = False,
    code_graph: bool = False,
    verbose: bool = False,
) -> None:
    normalized_proxy_url = _normalize_proxy_url(proxy_url, port)
    logger.debug(
        "run_init_targets: targets=%s global_scope=%s port=%s proxy_url=%s backend=%s memory=%s",
        targets,
        global_scope,
        port,
        normalized_proxy_url,
        backend,
        memory,
    )
    codex_uses_remote_proxy = "codex" in targets and not _proxy_url_uses_local_runtime(
        normalized_proxy_url
    )
    runtime_targets = [
        target
        for target in targets
        if target != "openclaw" and not (target == "codex" and codex_uses_remote_proxy)
    ]
    if not runtime_targets:
        profile = _runtime_profile(global_scope)
    else:
        profile = _ensure_runtime_manifest(
            global_scope=global_scope,
            targets=runtime_targets,
            port=port,
            backend=backend,
            anyllm_provider=anyllm_provider,
            region=region,
            memory=memory,
        )
    logger.debug("run_init_targets: using profile=%s", profile)
    for target in targets:
        logger.debug("run_init_targets: dispatching -> %s", target)
        if target == "claude":
            _init_claude(global_scope=global_scope, profile=profile, port=port)
        elif target == "copilot":
            _init_copilot(
                global_scope=global_scope,
                profile=profile,
                port=port,
                backend=backend,
                proxy_url=normalized_proxy_url,
            )
        elif target == "codex":
            _init_codex(
                global_scope=global_scope,
                profile=profile,
                port=port,
                proxy_url=normalized_proxy_url,
                serena=serena,
                no_serena=no_serena,
                no_tokensave=no_tokensave,
                code_graph=code_graph,
                verbose=verbose,
            )
        elif target == "openclaw":
            _init_openclaw(global_scope=global_scope, port=port)

    # Register the headroom MCP server with every targeted agent that has
    # a registrar implemented. Wave 1 covers Claude Code; subsequent waves
    # add Cursor / Codex / Continue / Cline / Windsurf / Goose without
    # touching the call sites.
    non_codex_targets = [target for target in targets if target != "codex"]
    _install_headroom_mcp_for_targets(targets=non_codex_targets, proxy_url=normalized_proxy_url)


def _install_headroom_mcp_for_targets(
    *, targets: list[str], proxy_url: str, force: bool = False
) -> None:
    """Install the headroom MCP server into each detected target agent."""
    from headroom.mcp_registry import format_results, install_everywhere

    if not targets:
        return

    results = install_everywhere(proxy_url=proxy_url, agents=targets, force=force)
    if not results:
        return

    lines = format_results(
        results,
        verbose=True,
        overwrite_hint=f"headroom mcp install --proxy-url {proxy_url} --force",
    )
    if lines:
        click.echo("\nMCP retrieve tool:")
        for line in lines:
            click.echo(line)


@main.group(invoke_without_command=True)
@click.option("-g", "--global", "global_scope", is_flag=True, help="Install for the current user.")
@click.option("--port", default=8787, type=int, show_default=True, help="Headroom proxy port.")
@click.option(
    "--proxy-url",
    default=None,
    help="Headroom proxy URL for provider and MCP routing (default: http://127.0.0.1:<port>).",
)
@click.option("--backend", default="anthropic", show_default=True, help="Proxy backend.")
@click.option("--anyllm-provider", default=None, help="Provider for any-llm backends.")
@click.option("--region", default=None, help="Cloud region for Bedrock / Vertex style backends.")
@click.option("--memory", is_flag=True, help="Enable persistent memory in the proxy runtime.")
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="Emit debug-level diagnostics to stderr (flag values, shutil.which results, "
    "file paths touched, subprocess invocations and exit codes).",
)
@click.pass_context
def init(
    ctx: click.Context,
    global_scope: bool,
    port: int,
    proxy_url: str | None,
    backend: str,
    anyllm_provider: str | None,
    region: str | None,
    memory: bool,
    verbose: bool,
) -> None:
    """Install durable Headroom integrations for supported agents."""
    if verbose:
        _enable_verbose_logging()
    logger.debug(
        "init: global_scope=%s port=%s proxy_url=%s backend=%s anyllm_provider=%s region=%s "
        "memory=%s invoked_subcommand=%s",
        global_scope,
        port,
        proxy_url,
        backend,
        anyllm_provider,
        region,
        memory,
        ctx.invoked_subcommand,
    )
    if ctx.invoked_subcommand is not None:
        ctx.obj = {
            "global_scope": global_scope,
            "port": port,
            "proxy_url": proxy_url,
            "backend": backend,
            "anyllm_provider": anyllm_provider,
            "region": region,
            "memory": memory,
            "verbose": verbose,
        }
        return

    targets = detect_init_targets(global_scope)
    if not targets:
        logger.debug("init: detect_init_targets returned empty; exiting with guided error")
        raise click.ClickException(_format_empty_detection_error(global_scope))
    logger.debug("init: detected targets=%s", targets)
    _run_init_targets(
        targets=targets,
        global_scope=global_scope,
        port=port,
        proxy_url=proxy_url,
        backend=backend,
        anyllm_provider=anyllm_provider,
        region=region,
        memory=memory,
    )


def _ctx_value(ctx: click.Context, key: str) -> Any:
    return (ctx.obj or {}).get(key)


@init.command("claude")
@click.pass_context
def init_claude(ctx: click.Context) -> None:
    """Install Claude Code durable hooks and provider routing."""
    _run_init_targets(
        targets=["claude"],
        global_scope=bool(_ctx_value(ctx, "global_scope")),
        port=int(_ctx_value(ctx, "port") or 8787),
        proxy_url=_ctx_value(ctx, "proxy_url"),
        backend=str(_ctx_value(ctx, "backend") or "anthropic"),
        anyllm_provider=_ctx_value(ctx, "anyllm_provider"),
        region=_ctx_value(ctx, "region"),
        memory=bool(_ctx_value(ctx, "memory")),
        verbose=bool(_ctx_value(ctx, "verbose")),
    )


@init.command("copilot")
@click.pass_context
def init_copilot(ctx: click.Context) -> None:
    """Install GitHub Copilot CLI durable hooks and provider routing."""
    _run_init_targets(
        targets=["copilot"],
        global_scope=bool(_ctx_value(ctx, "global_scope")),
        port=int(_ctx_value(ctx, "port") or 8787),
        proxy_url=_ctx_value(ctx, "proxy_url"),
        backend=str(_ctx_value(ctx, "backend") or "anthropic"),
        anyllm_provider=_ctx_value(ctx, "anyllm_provider"),
        region=_ctx_value(ctx, "region"),
        memory=bool(_ctx_value(ctx, "memory")),
        verbose=bool(_ctx_value(ctx, "verbose")),
    )


@init.command("codex")
@click.option(
    "--no-tokensave",
    is_flag=True,
    help="Skip the tokensave code-graph MCP server (primary coding-task compressor).",
)
@click.option(
    "--serena",
    is_flag=True,
    help="Explicitly install Serena MCP (default unless --no-serena is passed).",
)
@click.option("--no-serena", is_flag=True, help="Skip the Serena MCP server.")
@click.option(
    "--code-graph",
    is_flag=True,
    help="Force a tokensave code-graph index now.",
)
@click.pass_context
def init_codex(
    ctx: click.Context,
    no_tokensave: bool,
    serena: bool,
    no_serena: bool,
    code_graph: bool,
) -> None:
    """Install Codex durable hooks and provider routing."""
    _run_init_targets(
        targets=["codex"],
        global_scope=bool(_ctx_value(ctx, "global_scope")),
        port=int(_ctx_value(ctx, "port") or 8787),
        proxy_url=_ctx_value(ctx, "proxy_url"),
        backend=str(_ctx_value(ctx, "backend") or "anthropic"),
        anyllm_provider=_ctx_value(ctx, "anyllm_provider"),
        region=_ctx_value(ctx, "region"),
        memory=bool(_ctx_value(ctx, "memory")),
        serena=serena,
        no_serena=no_serena,
        no_tokensave=no_tokensave,
        code_graph=code_graph,
        verbose=bool(_ctx_value(ctx, "verbose")),
    )


@init.command("openclaw")
@click.pass_context
def init_openclaw(ctx: click.Context) -> None:
    """Install the durable OpenClaw Headroom plugin."""
    _run_init_targets(
        targets=["openclaw"],
        global_scope=bool(_ctx_value(ctx, "global_scope")),
        port=int(_ctx_value(ctx, "port") or 8787),
        proxy_url=_ctx_value(ctx, "proxy_url"),
        backend=str(_ctx_value(ctx, "backend") or "anthropic"),
        anyllm_provider=_ctx_value(ctx, "anyllm_provider"),
        region=_ctx_value(ctx, "region"),
        memory=bool(_ctx_value(ctx, "memory")),
        verbose=bool(_ctx_value(ctx, "verbose")),
    )


@init.group("hook", hidden=True)
def init_hook() -> None:
    """Internal hook helpers."""


@init_hook.command("ensure")
@click.option("--profile", default=None, help="Explicit deployment profile to ensure.")
@click.option("--marker", default=None, hidden=True)
def init_hook_ensure(profile: str | None, marker: str | None) -> None:
    """Best-effort ensure used by installed agent hooks."""
    del marker
    profiles: list[str] = []
    if profile:
        profiles.append(profile)
    else:
        local_profile = _local_profile()
        if load_manifest(local_profile) is not None:
            profiles.append(local_profile)
        elif load_manifest(_GLOBAL_PROFILE) is not None:
            profiles.append(_GLOBAL_PROFILE)
    for name in profiles:
        _ensure_profile_running(name)
