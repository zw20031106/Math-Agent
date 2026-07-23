from __future__ import annotations

from enum import Enum


class RuntimePhase(str, Enum):
    CREATED = "created"
    PARSED = "parsed"
    ROUTED = "routed"
    CONTEXT_READY = "context_ready"
    CANDIDATES_READY = "candidates_ready"
    EVIDENCE_READY = "evidence_ready"
    OBLIGATIONS_READY = "obligations_ready"
    VERIFIED = "verified"
    LEMMA_EXPANDED = "lemma_expanded"
    REVERIFIED = "reverified"
    ARBITRATED = "arbitrated"
    FORMATTED = "formatted"
    FINALIZED = "finalized"
    COMPLETED = "completed"
    FAILED = "failed"
    FALLBACK_COMPLETED = "fallback_completed"


class InvalidRuntimeTransition(RuntimeError):
    pass


_SUCCESSOR = {
    RuntimePhase.CREATED: RuntimePhase.PARSED,
    RuntimePhase.PARSED: RuntimePhase.ROUTED,
    RuntimePhase.ROUTED: RuntimePhase.CONTEXT_READY,
    RuntimePhase.CONTEXT_READY: RuntimePhase.CANDIDATES_READY,
    RuntimePhase.CANDIDATES_READY: RuntimePhase.EVIDENCE_READY,
    RuntimePhase.EVIDENCE_READY: RuntimePhase.OBLIGATIONS_READY,
    RuntimePhase.OBLIGATIONS_READY: RuntimePhase.VERIFIED,
    RuntimePhase.VERIFIED: RuntimePhase.LEMMA_EXPANDED,
    RuntimePhase.LEMMA_EXPANDED: RuntimePhase.REVERIFIED,
    RuntimePhase.REVERIFIED: RuntimePhase.ARBITRATED,
    RuntimePhase.ARBITRATED: RuntimePhase.FORMATTED,
    RuntimePhase.FORMATTED: RuntimePhase.FINALIZED,
    RuntimePhase.FINALIZED: RuntimePhase.COMPLETED,
    RuntimePhase.FAILED: RuntimePhase.FALLBACK_COMPLETED,
}

_FAILABLE = frozenset(RuntimePhase) - {
    RuntimePhase.FAILED,
    RuntimePhase.FALLBACK_COMPLETED,
}


def transition_allowed(current: RuntimePhase, target: RuntimePhase) -> bool:
    return _SUCCESSOR.get(current) == target or (
        current in _FAILABLE and target == RuntimePhase.FAILED
    )
