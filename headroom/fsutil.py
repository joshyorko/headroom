"""Encoding- and newline-safe text file I/O."""

from __future__ import annotations

import locale
import os
from pathlib import Path

_RAISE = object()


def read_text(path: str | os.PathLike[str], *, default: object = _RAISE) -> str:
    """Read text, preferring UTF-8 and falling back to the locale encoding."""
    try:
        raw = Path(path).read_bytes()
    except OSError:
        if default is not _RAISE:
            return default  # type: ignore[return-value]
        raise

    text: str | None = None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        loc = locale.getpreferredencoding(False)
        if loc and loc.lower().replace("-", "") != "utf8":
            try:
                text = raw.decode(loc)
            except (UnicodeDecodeError, LookupError):
                text = None
        if text is None:
            text = raw.decode("utf-8", errors="replace")

    return text.replace("\r\n", "\n").replace("\r", "\n")


def write_text(path: str | os.PathLike[str], content: str) -> None:
    """Write text as UTF-8 without translating line endings."""
    with Path(path).open("w", encoding="utf-8", newline="") as f:
        f.write(content)


def append_text(path: str | os.PathLike[str], content: str) -> None:
    """Append text as UTF-8 without translating line endings."""
    with Path(path).open("a", encoding="utf-8", newline="") as f:
        f.write(content)
