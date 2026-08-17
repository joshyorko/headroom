"""Byte-faithful outbound request body forwarding policy.

This module owns the small algebra used by Python proxy forwarders to decide
which bytes leave Headroom:

* unmutated body with original bytes -> byte-for-byte passthrough
* signed thinking blocks with original bytes -> byte-for-byte passthrough
* mutated body or missing original bytes -> canonical JSON bytes
* explicit rollback mode -> legacy httpx-style JSON bytes
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Literal

from headroom.proxy import python_forwarder_mode_policy

_PYTHON_FORWARDER_MODE_ENV = python_forwarder_mode_policy.PYTHON_FORWARDER_MODE_ENV

PythonForwarderMode = python_forwarder_mode_policy.PythonForwarderMode
OutboundBodySource = Literal["passthrough", "canonical", "legacy"]

_PYTHON_FORWARDER_MODE_DEFAULT = python_forwarder_mode_policy.PYTHON_FORWARDER_MODE_DEFAULT


@dataclass(frozen=True, slots=True)
class OutboundBody:
    """Concrete outbound body bytes plus their provenance."""

    content: bytes
    source: OutboundBodySource
    #: True when byte-faithful passthrough won over a mutated body, so every
    #: edit the handler made to ``body`` was discarded before the wire. Callers
    #: that gated a downstream decision on their own mutation (for example
    #: flipping ``stream`` to False to buffer a reply) MUST consult this — the
    #: request upstream actually sees is the client's original one.
    dropped_mutations: bool = False
    #: The ``BodyMutationTracker`` reasons discarded alongside it, when the
    #: caller supplied them. Empty when the caller passed no reason list.
    dropped_mutation_reasons: tuple[str, ...] = ()


def get_python_forwarder_mode() -> PythonForwarderMode:
    """Return the active Python-forwarder mode.

    Read at request time. Unknown values raise loudly per the no-silent-
    fallback build constraint. The ``legacy_json_kwarg`` value is an
    explicit operator opt-in for emergency rollback, not a fallback.
    """
    return python_forwarder_mode_policy.resolve_python_forwarder_mode(
        os.environ.get(_PYTHON_FORWARDER_MODE_ENV)
    )


def serialize_body_canonical(body: dict[str, Any]) -> bytes:
    """Re-serialize a request body deterministically with cache-stable formatting."""
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def has_signed_thinking_blocks(body: dict[str, Any]) -> bool:
    """Return whether message history contains Anthropic signed thinking blocks."""
    messages = body.get("messages")
    if not isinstance(messages, list):
        return False

    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") in {
                "thinking",
                "redacted_thinking",
            }:
                return True
    return False


class BodyMutationTracker:
    """Records whether a request body was mutated and why."""

    __slots__ = ("_mutated", "_reasons")

    def __init__(self) -> None:
        self._mutated: bool = False
        self._reasons: list[str] = []

    def mark_mutated(self, reason: str) -> None:
        """Mark the body as mutated and record the stable aggregation reason."""
        if not reason:
            raise ValueError("BodyMutationTracker.mark_mutated: reason must be non-empty")
        self._mutated = True
        if reason not in self._reasons:
            self._reasons.append(reason)

    @property
    def mutated(self) -> bool:
        return self._mutated

    @property
    def reasons(self) -> list[str]:
        return list(self._reasons)


def select_outbound_body(
    *,
    body: dict[str, Any],
    original_body_bytes: bytes | None,
    body_mutated: bool,
    forwarder_mode: PythonForwarderMode | None = None,
    mutation_reasons: list[str] | None = None,
) -> OutboundBody:
    """Select the exact bytes to forward upstream.

    ``mutation_reasons`` is optional and only used for reporting: when the
    signed-thinking passthrough overrides a mutated body, the discarded reasons
    are echoed back on the result so the call site can log what never made it
    upstream instead of silently claiming the edit landed.
    """
    mode = forwarder_mode if forwarder_mode is not None else get_python_forwarder_mode()
    if original_body_bytes is not None and has_signed_thinking_blocks(body):
        return OutboundBody(
            content=original_body_bytes,
            source="passthrough",
            dropped_mutations=body_mutated,
            dropped_mutation_reasons=tuple(mutation_reasons or ()) if body_mutated else (),
        )

    if mode == "legacy_json_kwarg":
        content = json.dumps(body, separators=(", ", ": "), ensure_ascii=True).encode("utf-8")
        return OutboundBody(content=content, source="legacy")

    if body_mutated or original_body_bytes is None:
        return OutboundBody(content=serialize_body_canonical(body), source="canonical")
    return OutboundBody(content=original_body_bytes, source="passthrough")


def prepare_outbound_body_bytes(
    *,
    body: dict[str, Any],
    original_body_bytes: bytes | None,
    body_mutated: bool,
    forwarder_mode: PythonForwarderMode | None = None,
    mutation_reasons: list[str] | None = None,
) -> tuple[bytes, OutboundBodySource]:
    """Compatibility tuple wrapper around :func:`select_outbound_body`.

    Keeps the two-value shape its existing callers unpack. Call
    :func:`select_outbound_body` directly when you need the dropped-mutation
    reporting.
    """
    outbound = select_outbound_body(
        body=body,
        original_body_bytes=original_body_bytes,
        body_mutated=body_mutated,
        forwarder_mode=forwarder_mode,
        mutation_reasons=mutation_reasons,
    )
    return outbound.content, outbound.source


def outbound_body_is_client_bytes(
    *,
    body: dict[str, Any],
    original_body_bytes: bytes | None,
) -> bool:
    """Return whether the wire body will be the client's original bytes.

    A handler that changes ``body`` to steer its own upstream call — the
    ``stream`` flip that buys a buffered reply is the load-bearing case — has to
    know that the signed-thinking passthrough will throw that change away and
    send the client's bytes verbatim. Asking before acting is cheaper than
    discovering it from a reply in the wrong wire format.

    Mirrors the first branch of :func:`select_outbound_body`; the forwarder mode
    is deliberately not consulted because that branch overrides it too.
    """
    return original_body_bytes is not None and has_signed_thinking_blocks(body)
