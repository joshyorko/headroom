"""Prompt-conditioned relevance split for KEEP/DROP compression decisions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from headroom.relevance import RelevanceScorer

__all__ = ["adaptive_threshold", "build_relevance_query", "plan_relevance_split", "segment"]


def build_relevance_query(user_query: str, tool_name: str = "", tool_args: str = "") -> str:
    """Compose the information-need query for relevance scoring."""
    parts: list[str] = []
    q = (user_query or "").strip()
    if q:
        parts.append(q)
    call = " ".join(p for p in ((tool_name or "").strip(), (tool_args or "").strip()) if p)
    if call:
        parts.append(call)
    return "\n".join(parts)


def segment(content: str, *, window: int = 8, max_chars: int = 1200) -> list[str]:
    """Partition ``content`` into coherent records."""
    lines = content.splitlines(keepends=True)
    if len(lines) <= 1:
        return [content] if content else []

    blocks: list[list[str]] = []
    cur: list[str] = []
    for ln in lines:
        cur.append(ln)
        if ln.strip() == "":
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)

    segments: list[str] = []
    for block in blocks:
        if len(block) <= window and sum(len(x) for x in block) <= max_chars:
            segments.append("".join(block))
            continue
        i = 0
        n = len(block)
        while i < n:
            j = min(i + window, n)
            while j < n and block[j][:1] in (" ", "\t"):
                j += 1
            segments.append("".join(block[i:j]))
            i = j
    return segments


def _otsu_threshold(values: list[float]) -> float:
    """Return Otsu's threshold for one score distribution."""
    xs = sorted(values)
    n = len(xs)
    total = sum(xs)
    w0 = 0.0
    sum0 = 0.0
    best_t = xs[0]
    best_var = -1.0
    for i in range(n - 1):
        w0 += 1
        sum0 += xs[i]
        w1 = n - w0
        m0 = sum0 / w0
        m1 = (total - sum0) / w1
        between = w0 * w1 * (m0 - m1) ** 2
        if between > best_var:
            best_var = between
            best_t = (xs[i] + xs[i + 1]) / 2.0
    return best_t


def adaptive_threshold(values: list[float], floor: float) -> float:
    """Data-driven KEEP/DROP cut for one output's relevance scores."""
    if len({round(v, 9) for v in values}) < 2:
        return floor
    return max(_otsu_threshold(values), floor)


def plan_relevance_split(
    content: str,
    query: str,
    scorer: RelevanceScorer,
    *,
    threshold: float,
    adaptive: bool = True,
    window: int = 8,
    max_chars: int = 1200,
    max_records: int | None = None,
) -> list[tuple[bool, str]]:
    """Split ``content`` into ordered ``(keep, text)`` runs by relevance."""
    if not query.strip():
        return [(True, content)]
    segs = segment(content, window=window, max_chars=max_chars)
    if len(segs) < 2 or (max_records and len(segs) > max_records):
        return [(True, content)]

    scores = scorer.score_batch(segs, query)
    cut = adaptive_threshold([s.score for s in scores], threshold) if adaptive else threshold
    runs: list[tuple[bool, str]] = []
    for seg, sc in zip(segs, scores):
        keep = sc.score >= cut
        if runs and runs[-1][0] == keep:
            runs[-1] = (keep, runs[-1][1] + seg)
        else:
            runs.append((keep, seg))
    return runs
