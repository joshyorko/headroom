"""Issue #746: keep Claude Code's on-demand tool loading active through the proxy.

Covers the two halves of the fix:

* ``headroom wrap claude`` injects ``ENABLE_TOOL_SEARCH`` into the launched
  Claude Code environment (with correct precedence / validation), and
* the proxy detects a Claude Code request that is *not* deferring tools and
  emits a single actionable hint for users who run ``claude`` manually.
"""

from __future__ import annotations

import pytest

from headroom.cli.wrap import (
    _TOOL_SEARCH_DEFAULT,
    _TOOL_SEARCH_ENV,
    _configure_tool_search_env,
    _normalize_tool_search_mode,
)
from headroom.proxy.helpers import (
    claude_code_tool_search_inactive,
    format_tool_search_disabled_hint,
    reset_tool_search_hint_state,
    take_tool_search_hint_slot,
    tool_search_hint_pending,
)

# ---------------------------------------------------------------------------
# wrap: ENABLE_TOOL_SEARCH value normalization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("true", "true"),
        ("TRUE", "true"),
        (" on ", "on"),
        ("1", "1"),
        ("false", "false"),
        ("off", "off"),
        ("auto", "auto"),
        ("auto:0", "auto:0"),
        ("auto:50", "auto:50"),
        ("auto:100", "auto:100"),
    ],
)
def test_normalize_tool_search_mode_accepts_valid(value: str, expected: str) -> None:
    assert _normalize_tool_search_mode(value) == expected


@pytest.mark.parametrize("value", ["yep", "auto:", "auto:101", "auto:-1", "auto:abc", ""])
def test_normalize_tool_search_mode_rejects_invalid(value: str) -> None:
    import click

    with pytest.raises(click.ClickException):
        _normalize_tool_search_mode(value)


# ---------------------------------------------------------------------------
# wrap: ENABLE_TOOL_SEARCH injection precedence
# ---------------------------------------------------------------------------


def test_configure_injects_default_when_unset() -> None:
    env: dict[str, str] = {}
    result = _configure_tool_search_env(env, None)
    assert result == _TOOL_SEARCH_DEFAULT
    assert env[_TOOL_SEARCH_ENV] == _TOOL_SEARCH_DEFAULT


def test_configure_respects_existing_env_value() -> None:
    env = {_TOOL_SEARCH_ENV: "auto:30"}
    result = _configure_tool_search_env(env, None)
    # None signals "left the user's value untouched".
    assert result is None
    assert env[_TOOL_SEARCH_ENV] == "auto:30"


def test_configure_flag_overrides_existing_env_value() -> None:
    env = {_TOOL_SEARCH_ENV: "false"}
    result = _configure_tool_search_env(env, "auto")
    assert result == "auto"
    assert env[_TOOL_SEARCH_ENV] == "auto"


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_configure_overrides_blank_env_value(blank: str) -> None:
    # Claude Code treats an empty ENABLE_TOOL_SEARCH as unset, so a blank value
    # must be replaced with the default rather than forwarded as a no-op.
    env = {_TOOL_SEARCH_ENV: blank}
    result = _configure_tool_search_env(env, None)
    assert result == _TOOL_SEARCH_DEFAULT
    assert env[_TOOL_SEARCH_ENV] == _TOOL_SEARCH_DEFAULT


def test_configure_flag_validated() -> None:
    import click

    with pytest.raises(click.ClickException):
        _configure_tool_search_env({}, "nonsense")


# ---------------------------------------------------------------------------
# proxy: detect a Claude Code request that is not deferring tools
# ---------------------------------------------------------------------------

_TOOLS = [
    {"name": "Read", "description": "read a file", "input_schema": {"type": "object"}},
    {"name": "Bash", "description": "run a command", "input_schema": {"type": "object"}},
]


def test_inactive_true_for_eager_claude_code() -> None:
    assert claude_code_tool_search_inactive(client="claude-code", tools=_TOOLS, anthropic_beta=None)


def test_inactive_false_when_tool_search_tool_present() -> None:
    tools = [*_TOOLS, {"type": "tool_search_tool_regex_20251119", "name": "tool_search_tool_regex"}]
    assert not claude_code_tool_search_inactive(
        client="claude-code", tools=tools, anthropic_beta=None
    )


def test_inactive_false_when_beta_header_present() -> None:
    assert not claude_code_tool_search_inactive(
        client="claude-code",
        tools=_TOOLS,
        anthropic_beta="context-1m-2025-08-07,advanced-tool-use-2025-11-20",
    )


def test_inactive_false_for_other_clients() -> None:
    assert not claude_code_tool_search_inactive(client="codex", tools=_TOOLS, anthropic_beta=None)
    assert not claude_code_tool_search_inactive(client=None, tools=_TOOLS, anthropic_beta=None)


def test_inactive_false_when_no_tools() -> None:
    assert not claude_code_tool_search_inactive(client="claude-code", tools=[], anthropic_beta=None)
    assert not claude_code_tool_search_inactive(
        client="claude-code", tools=None, anthropic_beta=None
    )


# ---------------------------------------------------------------------------
# proxy: hint content + one-time guard
# ---------------------------------------------------------------------------


def test_hint_message_is_actionable() -> None:
    msg = format_tool_search_disabled_hint(_TOOLS)
    assert "ENABLE_TOOL_SEARCH=true" in msg
    assert "746" in msg
    assert str(len(_TOOLS)) in msg


def test_hint_slot_fires_once() -> None:
    reset_tool_search_hint_state()
    try:
        assert tool_search_hint_pending() is True
        assert take_tool_search_hint_slot() is True
        # Once consumed, the cheap gate flips so the hot path stops scanning.
        assert tool_search_hint_pending() is False
        assert take_tool_search_hint_slot() is False
        assert take_tool_search_hint_slot() is False
    finally:
        reset_tool_search_hint_state()


# ---------------------------------------------------------------------------
# Server-side Tool Search injection for plain-API clients (opencode)
# ---------------------------------------------------------------------------

from headroom.proxy.helpers import (  # noqa: E402
    _TOOL_SEARCH_DEFAULT_NAME,
    _TOOL_SEARCH_DEFAULT_TYPE,
    _TOOL_SEARCH_MIN_TOOLS,
    inject_tool_search_deferral,
)


def _tools(n: int, *, core_first: int = 0) -> list[dict]:
    core = ["bash", "read", "write", "edit", "grep"]
    out: list[dict] = []
    for i in range(n):
        name = core[i] if i < core_first and i < len(core) else f"mcp_tool_{i}"
        out.append({"name": name, "description": f"tool {i}", "input_schema": {}})
    return out


def test_inject_defers_non_core_and_injects_search_tool() -> None:
    tools = _tools(20, core_first=3)  # bash/read/write resident, rest deferred
    out = inject_tool_search_deferral(tools)
    assert out is not tools
    # search tool injected, non-deferred, correct shape
    search = out[0]
    assert search == {"type": _TOOL_SEARCH_DEFAULT_TYPE, "name": _TOOL_SEARCH_DEFAULT_NAME}
    assert "defer_loading" not in search
    # core tools stay resident; non-core deferred
    by_name = {t.get("name"): t for t in out if "name" in t}
    assert by_name["bash"].get("defer_loading") is None
    assert by_name["mcp_tool_5"].get("defer_loading") is True
    # at least one non-deferred real tool remains (Anthropic 400s otherwise)
    assert any(not t.get("type") and not t.get("defer_loading") for t in out)


def test_noop_below_min_tools() -> None:
    tools = _tools(_TOOL_SEARCH_MIN_TOOLS - 1)
    assert inject_tool_search_deferral(tools) is tools


def test_noop_when_client_already_uses_tool_search() -> None:
    tools = _tools(20) + [{"type": "tool_search_tool_regex_20251119", "name": "x"}]
    assert inject_tool_search_deferral(tools) is tools


def test_noop_when_nothing_to_defer() -> None:
    # every tool is core -> nothing deferred -> cache prefix untouched
    core = [
        "bash",
        "read",
        "write",
        "edit",
        "multiedit",
        "glob",
        "grep",
        "task",
        "todowrite",
        "todoread",
        "webfetch",
        "skill",
    ]
    tools = [{"name": n, "input_schema": {}} for n in core]
    assert inject_tool_search_deferral(tools) is tools


def test_cache_control_moved_off_deferred_tool_to_last_resident() -> None:
    tools = _tools(20, core_first=3)
    # the client's tools cache breakpoint sits on a tool we will defer
    tools[10]["cache_control"] = {"type": "ephemeral"}
    out = inject_tool_search_deferral(tools)
    # no deferred tool may carry cache_control (Anthropic 400s)
    assert all("cache_control" not in t for t in out if t.get("defer_loading"))
    # exactly one resident real tool now carries the moved breakpoint
    resident_cc = [
        t
        for t in out
        if not t.get("type") and not t.get("defer_loading") and t.get("cache_control")
    ]
    assert len(resident_cc) == 1


def test_non_dict_and_typed_tools_stay_resident() -> None:
    tools = _tools(15, core_first=2)
    tools.append({"type": "web_search_20250305", "name": "web_search"})
    out = inject_tool_search_deferral(tools)
    typed = [t for t in out if t.get("type") == "web_search_20250305"]
    assert len(typed) == 1 and typed[0].get("defer_loading") is None


# ---------------------------------------------------------------------------
# PascalCase clients (Claude Code). The core-tool exemption is spelled in
# lowercase, so an exact-match comparison never fired for Claude Code: every
# tool was deferred, including Claude Code's own ``ToolSearch``.
# ---------------------------------------------------------------------------


def _claude_code_tools() -> list[dict]:
    """Claude Code's surface: PascalCase built-ins, its ToolSearch, MCP tools."""
    names = ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "ToolSearch"] + [
        f"mcp__srv__t{i}" for i in range(12)
    ]
    return [{"name": n, "description": n, "input_schema": {}} for n in names]


def test_core_tools_match_case_insensitively() -> None:
    # Without a case-insensitive match, routine edit/read/run loops each pay a
    # search round-trip — the exact thing _TOOL_SEARCH_CORE_TOOLS exists to avoid.
    out = inject_tool_search_deferral(_claude_code_tools())
    by_name = {t.get("name"): t for t in out if "name" in t}
    for name in ("Bash", "Read", "Write", "Edit", "Glob", "Grep"):
        assert by_name[name].get("defer_loading") is None, name
    # MCP tools are still deferred — the token saving is preserved.
    assert by_name["mcp__srv__t0"].get("defer_loading") is True


def test_client_tool_search_tool_is_never_deferred() -> None:
    # ToolSearch is the client's own schema fetcher for tools that never appear
    # in the request body (TaskCreate, WebFetch, …). Deferring it hides the only
    # tool that can load them, so they become permanently unreachable.
    out = inject_tool_search_deferral(_claude_code_tools())
    by_name = {t.get("name"): t for t in out if "name" in t}
    assert by_name["ToolSearch"].get("defer_loading") is None


def test_resident_real_tool_survives_pascal_case_surface() -> None:
    # The injected search tool is typed and does not satisfy the invariant on its
    # own; Anthropic 400s when every real tool is deferred.
    out = inject_tool_search_deferral(_claude_code_tools())
    assert any(not t.get("type") and not t.get("defer_loading") for t in out)


# ---------------------------------------------------------------------------
# Tool-search history repair (#2805)
#
# Anthropic validates every tool_reference in the transcript against the
# request's tools array. Claude Code replays one transcript across requests
# with DIFFERENT tools arrays (main loop vs prompt-type Stop hook evaluator),
# so the side-request 400s with "Tool reference 'X' not found in available
# tools". The repair drops blocks a request cannot support.
# ---------------------------------------------------------------------------

from headroom.proxy.helpers import (  # noqa: E402
    strip_unsupported_tool_search_blocks,
)

_SEARCH_TOOL = {"type": _TOOL_SEARCH_DEFAULT_TYPE, "name": _TOOL_SEARCH_DEFAULT_NAME}


def _poisoned_transcript() -> list[dict]:
    """A transcript as Claude Code stores it after one server-side tool search."""
    return [
        {"role": "user", "content": [{"type": "text", "text": "ask the user"}]},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Searching for a tool."},
                {
                    "type": "server_tool_use",
                    "id": "srvtoolu_01ABC",
                    "name": _TOOL_SEARCH_DEFAULT_NAME,
                    "input": {"pattern": "question|ask"},
                },
                {
                    "type": "tool_search_tool_result",
                    "tool_use_id": "srvtoolu_01ABC",
                    "content": {
                        "type": "tool_search_tool_search_result",
                        "tool_references": [
                            {"type": "tool_reference", "tool_name": "AskUserQuestion"}
                        ],
                    },
                },
                {"type": "text", "text": "Found it."},
            ],
        },
    ]


def test_repair_drops_blocks_the_hook_evaluator_cannot_resolve() -> None:
    # The Stop hook evaluator replays the transcript with a small tools array
    # that has neither the search tool nor AskUserQuestion -> upstream 400.
    messages, removed = strip_unsupported_tool_search_blocks(
        _poisoned_transcript(), [{"name": "Read", "input_schema": {}}]
    )
    assert removed == 2  # server_tool_use + tool_search_tool_result
    kinds = [b["type"] for b in messages[1]["content"]]
    assert kinds == ["text", "text"]  # surrounding assistant text survives
    assert messages[0]["content"][0]["text"] == "ask the user"


def test_repair_is_noop_on_the_main_loop() -> None:
    # Same transcript, but the request carries the injected search tool AND the
    # referenced tool: nothing to repair, and the object is returned by identity
    # so the outbound prefix (and its cache) is untouched.
    transcript = _poisoned_transcript()
    messages, removed = strip_unsupported_tool_search_blocks(
        transcript,
        [_SEARCH_TOOL, {"name": "AskUserQuestion", "input_schema": {}, "defer_loading": True}],
    )
    assert removed == 0
    assert messages is transcript


def test_repair_drops_a_turn_left_with_no_blocks() -> None:
    # An assistant turn that was ONLY the search round-trip must be removed, not
    # forwarded with an empty content array (which Anthropic also rejects).
    transcript = _poisoned_transcript()
    transcript[1]["content"] = transcript[1]["content"][1:3]
    messages, removed = strip_unsupported_tool_search_blocks(transcript, [])
    assert removed == 2
    assert len(messages) == 1
    assert messages[0]["role"] == "user"


def test_repair_leaves_other_server_tools_alone() -> None:
    # web_search / code execution use the same block type and stay untouched.
    transcript = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "server_tool_use",
                    "id": "srvtoolu_web",
                    "name": "web_search",
                    "input": {"query": "x"},
                },
                {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_web", "content": []},
            ],
        }
    ]
    messages, removed = strip_unsupported_tool_search_blocks(transcript, [])
    assert removed == 0
    assert messages is transcript


def test_repair_is_idempotent() -> None:
    # Deterministic: repairing an already-repaired transcript is a no-op, so a
    # session's forwarded prefix stays byte-stable turn over turn.
    once, _ = strip_unsupported_tool_search_blocks(_poisoned_transcript(), [])
    twice, removed = strip_unsupported_tool_search_blocks(once, [])
    assert removed == 0
    assert twice is once


def test_repair_strips_search_history_when_only_the_tool_is_missing() -> None:
    # References all resolve, but the request has no tool_search tool at all
    # (e.g. deferral skipped below _TOOL_SEARCH_MIN_TOOLS) -- history still
    # cannot be supported, so it goes.
    _, removed = strip_unsupported_tool_search_blocks(
        _poisoned_transcript(), [{"name": "AskUserQuestion", "input_schema": {}}]
    )
    assert removed == 2
