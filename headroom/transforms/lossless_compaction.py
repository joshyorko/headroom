"""Format-native, reversible lossless compaction for no-CCR proxy mode.

Every helper here is pure stdlib and keeps its output looking like its own
type: grep stays grep, logs stay logs, diffs stay diffs. No retrieval marker
(``<<ccr:...>>`` / ``Retrieve ...``) is ever emitted, so the proxy needs no MCP
retrieve round-trip to stay recoverable.

The reversible transforms ship with exact inverses and are self-checked at
runtime by :func:`compact_lossless`: if a round-trip does not reproduce the
original (modulo intentionally-dropped non-semantic bits such as ANSI color)
or the result is not actually smaller, the original content is returned
unchanged. Nothing here raises.
"""

from __future__ import annotations

import re

__all__ = [
    "strip_ansi",
    "collapse_runs",
    "expand_runs",
    "is_run_collapsed",
    "search_heading",
    "search_unheading",
    "diff_strip_index",
    "compact_lossless",
]

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_RUN_MARKER_RE = re.compile(r"^\.\.\. \(repeated (\d+) times\)$")
_GREP_ROW_RE = re.compile(r"^(?P<path>[^\n:]+):(?P<line>\d+):(?P<content>.*)$")
_HEADING_ROW_RE = re.compile(r"^(?P<line>\d+):(?P<content>.*)$")
_DIFF_INDEX_RE = re.compile(r"^index [0-9a-fA-F]+\.\.[0-9a-fA-F]+( [0-7]+)?$")


def strip_ansi(text: str) -> str:
    """Remove ANSI CSI/SGR color escape sequences."""
    return _ANSI_RE.sub("", text)


def _split_keep_trailing(text: str) -> tuple[list[str], bool]:
    """Split into lines and remember whether a trailing newline was present."""
    if text == "":
        return [], False
    had_trailing = text.endswith("\n")
    body = text[:-1] if had_trailing else text
    return body.split("\n"), had_trailing


def _join(lines: list[str], had_trailing: bool) -> str:
    out = "\n".join(lines)
    if had_trailing:
        out += "\n"
    return out


def collapse_runs(text: str) -> str:
    """Collapse runs of >=2 identical consecutive lines."""
    lines, had_trailing = _split_keep_trailing(text)
    if not lines:
        return text
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        j = i
        while j + 1 < n and lines[j + 1] == lines[i]:
            j += 1
        run_len = j - i + 1
        if run_len >= 2:
            out.append(lines[i])
            out.append(f"... (repeated {run_len} times)")
        else:
            out.append(lines[i])
        i = j + 1
    return _join(out, had_trailing)


def expand_runs(text: str) -> str:
    """Exact inverse of :func:`collapse_runs`."""
    lines, had_trailing = _split_keep_trailing(text)
    if not lines:
        return text
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if i + 1 < n:
            m = _RUN_MARKER_RE.match(lines[i + 1])
            if m:
                count = int(m.group(1))
                out.extend([line] * count)
                i += 2
                continue
        out.append(line)
        i += 1
    return _join(out, had_trailing)


def is_run_collapsed(text: str) -> bool:
    """True if any run-collapse marker line is present."""
    for line in text.split("\n"):
        if _RUN_MARKER_RE.match(line):
            return True
    return False


def search_heading(text: str) -> str:
    """Convert grep ``path:line:content`` rows into ripgrep heading form."""
    lines, had_trailing = _split_keep_trailing(text)
    if not lines:
        return text
    out: list[str] = []
    current_path: str | None = None
    for line in lines:
        m = _GREP_ROW_RE.match(line)
        if m:
            path = m.group("path")
            if path != current_path:
                out.append(path)
                current_path = path
            out.append(f"{m.group('line')}:{m.group('content')}")
        else:
            out.append(line)
            current_path = None
    return _join(out, had_trailing)


def search_unheading(text: str) -> str:
    """Exact inverse of :func:`search_heading`."""
    lines, had_trailing = _split_keep_trailing(text)
    if not lines:
        return text
    out: list[str] = []
    current_path: str | None = None
    n = len(lines)
    i = 0
    while i < n:
        line = lines[i]
        data = _HEADING_ROW_RE.match(line)
        if current_path is not None and data:
            out.append(f"{current_path}:{data.group('line')}:{data.group('content')}")
            i += 1
            continue
        if not data and i + 1 < n and _HEADING_ROW_RE.match(lines[i + 1]):
            current_path = line
            i += 1
            continue
        current_path = None
        out.append(line)
        i += 1
    return _join(out, had_trailing)


def diff_strip_index(text: str) -> str:
    """Drop ``index <sha>..<sha>`` lines from a unified diff."""
    lines, had_trailing = _split_keep_trailing(text)
    if not lines:
        return text
    out = [line for line in lines if not _DIFF_INDEX_RE.match(line)]
    return _join(out, had_trailing)


# A whole-line file path: optional ``./``/``../`` root, >=1 directory segment,
# then a basename. No whitespace or ':' (so grep ``path:line:content`` rows —
# handled by search_heading — are excluded). Directory-only lines (trailing '/')
# don't match (empty basename), which keeps the fold unambiguous.
_PATH_ROW_RE = re.compile(r"^(?P<dir>(?:\.{0,2}/)?(?:[^/\s:]+/)+)(?P<base>[^/\s:]+)$")


def path_heading(text: str) -> str:
    """Fold a *pure* file-path listing (``find`` / ``ls -1`` / ``rg -l`` output)
    into ripgrep-heading form: each parent directory printed once on its own
    line (ending in ``/``), then the bare basenames beneath it.

    Reversibility is not assumed here — ``compact_lossless`` verifies the exact
    round-trip via :func:`path_unheading` and discards the fold on any mismatch
    (e.g. a stray no-slash line mistaken for a basename), so mixed content is
    always safe. Requires >=2 path rows or there is nothing to group.
    Complements ``search_heading``, which only handles the ``path:line:content``
    grep shape, not plain path lists.
    """
    lines, had_trailing = _split_keep_trailing(text)
    if sum(1 for ln in lines if _PATH_ROW_RE.match(ln)) < 2:
        return text
    out: list[str] = []
    current: str | None = None
    for line in lines:
        m = _PATH_ROW_RE.match(line)
        if m:
            d = m.group("dir")
            if d != current:
                out.append(d)
                current = d
            out.append(m.group("base"))
        else:  # blank line inside/around the listing
            out.append(line)
            current = None
    return _join(out, had_trailing)


def path_unheading(text: str) -> str:
    """Exact inverse of :func:`path_heading`.

    A *header* is a line ending in ``/`` immediately followed by a basename row
    (a non-empty line with no ``/``); it is consumed and re-prefixed onto each
    following basename row until a blank line or another header.
    """
    lines, had_trailing = _split_keep_trailing(text)
    if not lines:
        return text
    out: list[str] = []
    current: str | None = None
    n = len(lines)
    i = 0
    while i < n:
        line = lines[i]
        is_base = line != "" and "/" not in line
        if current is not None and is_base:
            out.append(current + line)
            i += 1
            continue
        if line.endswith("/") and i + 1 < n and lines[i + 1] != "" and "/" not in lines[i + 1]:
            current = line
            i += 1
            continue
        current = None
        out.append(line)
        i += 1
    return _join(out, had_trailing)


def _smaller(candidate: str, original: str) -> bool:
    return len(candidate) < len(original)


def compact_lossless(content: str, kind: str) -> str:
    """Dispatch format-native lossless compaction by ``kind``."""
    if not content:
        return content
    try:
        if kind == "log":
            baseline = strip_ansi(content)
            candidate = collapse_runs(baseline)
            if expand_runs(candidate) != baseline:
                return content
            return candidate if _smaller(candidate, content) else content

        if kind == "search":
            candidate = search_heading(content)
            if search_unheading(candidate) != content:
                return content
            return candidate if _smaller(candidate, content) else content

        if kind == "paths":
            # Pure path listings (find/ls -1/rg -l): fold repeated parent dirs.
            candidate = path_heading(content)
            if path_unheading(candidate) != content:
                return content
            return candidate if _smaller(candidate, content) else content

        if kind == "diff":
            candidate = diff_strip_index(content)
            return candidate if _smaller(candidate, content) else content

        if kind == "text":
            candidate = collapse_runs(content)
            if expand_runs(candidate) != content:
                return content
            return candidate if _smaller(candidate, content) else content
    except Exception:
        return content
    return content
