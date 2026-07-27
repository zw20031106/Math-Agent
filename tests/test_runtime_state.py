from __future__ import annotations

import pytest

from mathforge.config import HarnessConfig
from mathforge.harness.budget import CallBudget
from mathforge.harness.session import create_session
from mathforge.harness.state import InvalidRuntimeTransition, RuntimePhase
from mathforge.runtime import MathForgeHarness
from tests.fake_client import FakeClient


_SUCCESS_PHASES = [
    RuntimePhase.CREATED,
    RuntimePhase.PARSED,
    RuntimePhase.ROUTED,
    RuntimePhase.CONTEXT_READY,
    RuntimePhase.CANDIDATES_READY,
    RuntimePhase.EVIDENCE_READY,
    RuntimePhase.OBLIGATIONS_READY,
    RuntimePhase.PRECHECKED,
    RuntimePhase.LEMMA_EXPANDED,
    RuntimePhase.VERIFIED,
    RuntimePhase.ARBITRATED,
    RuntimePhase.FORMATTED,
    RuntimePhase.FINALIZED,
    RuntimePhase.COMPLETED,
]


def _minimal_config() -> HarnessConfig:
    return HarnessConfig(
        profile="test",
        status="test",
        max_model_calls=1,
        enable_router=False,
        enable_skills=False,
        enable_alternatives=False,
        enable_tools=False,
        enable_evidence=False,
        enable_proof_obligations=False,
        enable_verifier=False,
        enable_memory=False,
        enable_lemma_loop=False,
        enable_rag=False,
        enable_repair=False,
        enable_finalizer=False,
    )


def test_runtime_state_machine_accepts_only_declared_transitions():
    session = create_session("x", {}, CallBudget(1))
    for expected, target in zip(_SUCCESS_PHASES, _SUCCESS_PHASES[1:]):
        session.transition(expected, target, reason="test")
    assert session.phase == RuntimePhase.COMPLETED
    assert [item["to_phase"] for item in session.phase_history] == [
        phase.value for phase in _SUCCESS_PHASES[1:]
    ]

    repaired = create_session("x", {}, CallBudget(1))
    for expected, target in zip(_SUCCESS_PHASES, _SUCCESS_PHASES[1:]):
        if expected == RuntimePhase.VERIFIED:
            repaired.transition(
                RuntimePhase.VERIFIED,
                RuntimePhase.REVERIFIED,
                reason="post_verifier_repair_revalidated",
            )
            repaired.transition(
                RuntimePhase.REVERIFIED,
                RuntimePhase.ARBITRATED,
                reason="test",
            )
            continue
        if repaired.phase == expected:
            repaired.transition(expected, target, reason="test")
    assert repaired.phase == RuntimePhase.COMPLETED

    another = create_session("x", {}, CallBudget(1))
    with pytest.raises(InvalidRuntimeTransition):
        another.transition(
            RuntimePhase.CREATED,
            RuntimePhase.CANDIDATES_READY,
            reason="illegal_skip",
        )


@pytest.mark.parametrize(
    "phase",
    [item for item in RuntimePhase if item not in {
        RuntimePhase.FAILED,
        RuntimePhase.FALLBACK_COMPLETED,
    }],
)
def test_every_runtime_phase_can_fail_into_the_safe_terminal_path(phase):
    session = create_session("x", {}, CallBudget(1))
    path = list(_SUCCESS_PHASES)
    if phase == RuntimePhase.REVERIFIED:
        path.insert(path.index(RuntimePhase.ARBITRATED), RuntimePhase.REVERIFIED)
    for expected, target in zip(path, path[1:]):
        if session.phase == phase:
            break
        session.transition(expected, target, reason="reach_test_phase")
    session.transition(phase, RuntimePhase.FAILED, reason="test_failure")
    session.transition(
        RuntimePhase.FAILED,
        RuntimePhase.FALLBACK_COMPLETED,
        reason="fallback",
    )
    assert session.phase == RuntimePhase.FALLBACK_COMPLETED


def test_disabled_features_use_legal_skip_transitions():
    result = MathForgeHarness(FakeClient(), _minimal_config()).solve("1 + 1", {})
    transitions = [
        event["to_phase"]
        for event in result["trace"]
        if event["event"] == "phase_transition"
    ]
    assert transitions == [phase.value for phase in _SUCCESS_PHASES[1:]]
    assert result["run_metrics"]["final_phase"] == RuntimePhase.COMPLETED.value


def test_failure_transitions_to_safe_fallback_terminal_state():
    result = MathForgeHarness(FakeClient(fail=True), _minimal_config()).solve("x", {})
    transitions = [
        event
        for event in result["trace"]
        if event["event"] == "phase_transition"
    ]
    assert [event["to_phase"] for event in transitions[-2:]] == [
        RuntimePhase.FAILED.value,
        RuntimePhase.FALLBACK_COMPLETED.value,
    ]
    fallback = next(event for event in result["trace"] if event["event"] == "fallback_used")
    assert fallback["reason"] == "all_candidates_failed"
    assert fallback["error_code"] == "all_candidates_failed"
    assert fallback["failed_phase"] == RuntimePhase.CONTEXT_READY.value
    assert result["run_metrics"]["final_phase"] == RuntimePhase.FALLBACK_COMPLETED.value
