"""overlay_cached_prefix: freeze must forward the CACHED (compressed) bytes.

The freeze path can emit the agent's ORIGINAL bytes for a frozen message, but
the provider cached whatever we FORWARDED last turn (the compressed form).
Forwarding original then mismatches the cached prefix and busts the prompt cache
(observed: 100% of misses were this ``prefix_change``, ~56% of all cache-writes).
``overlay_cached_prefix`` replays the previously-forwarded prefix byte-identical
so the cache still hits — in BOTH proxy modes.
"""

from headroom.cache.prefix_tracker import overlay_cached_prefix


def M(role, text):
    return {"role": role, "content": text}


# Previous turn: 2 messages. Original was big; we FORWARDED the compressed form,
# so that compressed form is what the provider cached.
PREV_ORIG = [M("user", "READ foo.py:\n<2000 original lines>"), M("assistant", "ok")]
PREV_FWD = [M("user", "READ foo.py:\n<compressed>"), M("assistant", "ok")]
# This turn: agent appended one new message (append-only growth).
CUR_ORIG = PREV_ORIG + [M("user", "grep result:\n<800 original lines>")]
# What apply() produced in the buggy freeze path: ORIGINAL bytes for the frozen
# prefix (== PREV_ORIG) + compressed new tail.
OPTIMIZED_BUGGY = [PREV_ORIG[0], PREV_ORIG[1], M("user", "grep result:\n<compressed>")]


def test_replays_cached_compressed_prefix_byte_identical():
    out = overlay_cached_prefix(OPTIMIZED_BUGGY, CUR_ORIG, PREV_ORIG, PREV_FWD)
    # The frozen prefix now equals what the provider cached (compressed), NOT the
    # agent's original bytes → cache hits instead of busting.
    assert out[:2] == PREV_FWD
    assert out[:2] != PREV_ORIG
    # This turn's compressed tail is preserved.
    assert out[2] == OPTIMIZED_BUGGY[2]
    assert len(out) == len(CUR_ORIG)


def test_is_a_noop_relative_to_cache_when_already_correct():
    # If the freeze path already forwarded the compressed (cached) prefix, the
    # overlay reproduces exactly that — idempotent.
    already_correct = [PREV_FWD[0], PREV_FWD[1], M("user", "grep result:\n<compressed>")]
    out = overlay_cached_prefix(already_correct, CUR_ORIG, PREV_ORIG, PREV_FWD)
    assert out == already_correct


def test_not_append_only_returns_unchanged():
    # An early message changed → previous forwarded bytes may not correspond to
    # the same positions; do NOT overlay (accept a possible bust over corruption).
    changed = [M("user", "TOTALLY DIFFERENT"), PREV_ORIG[1], M("user", "x")]
    out = overlay_cached_prefix(OPTIMIZED_BUGGY, changed, PREV_ORIG, PREV_FWD)
    assert out == OPTIMIZED_BUGGY


def test_no_previous_state_returns_unchanged():
    assert overlay_cached_prefix(OPTIMIZED_BUGGY, CUR_ORIG, None, None) == OPTIMIZED_BUGGY
    assert overlay_cached_prefix(OPTIMIZED_BUGGY, CUR_ORIG, [], []) == OPTIMIZED_BUGGY


def test_forwarded_count_mismatch_returns_unchanged():
    # Defensive: not exactly one forwarded message per original → bail.
    assert (
        overlay_cached_prefix(OPTIMIZED_BUGGY, CUR_ORIG, PREV_ORIG, PREV_FWD[:1]) == OPTIMIZED_BUGGY
    )


def test_shorter_current_or_optimized_returns_unchanged():
    assert overlay_cached_prefix([M("user", "x")], [M("user", "x")], PREV_ORIG, PREV_FWD) == [
        M("user", "x")
    ]


def test_cache_hit_property_prefix_matches_last_forward():
    # The invariant that guarantees a cache hit: forwarded[:n] this turn ==
    # forwarded[:n] last turn (== what the provider cached).
    out = overlay_cached_prefix(OPTIMIZED_BUGGY, CUR_ORIG, PREV_ORIG, PREV_FWD)
    n = len(PREV_FWD)
    assert out[:n] == PREV_FWD  # exact byte-identical prefix → provider cache hit
