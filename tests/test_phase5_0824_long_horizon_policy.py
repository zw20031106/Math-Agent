from __future__ import annotations

from mathforge.agent_runtime.autonomy import AgentProgressTracker
from mathforge.agent_runtime.protocol import AgentTurnPayload
from mathforge.harness.model_policy import (
    stage_sequence_feasible,
    stage_sequence_feasible_parallel,
    stage_sequence_reserve_seconds_parallel,
)


def _payload(*, action: str, obligations: list[str], evidence: list[str]):
    return AgentTurnPayload(
        protocol_version="1.0",
        task_result_type="ProgressArtifact",
        action=action,
        public_state_delta={
            "unresolved_obligation_ids": obligations,
            "evidence_ids": evidence,
        },
        result_payload={},
        outbound_intents=(),
        progress_summary="public progress",
        stop_reason="",
    )


def test_parallel_reserve_does_not_serialize_solver_exploration():
    stages = ["solver_candidate_standard"] * 3
    assert stage_sequence_reserve_seconds_parallel(
        stages,
        30,
        worker_count=3,
    ) < stage_sequence_reserve_seconds_parallel(
        stages,
        30,
        worker_count=1,
    )
    assert not stage_sequence_feasible(
        stages,
        remaining_seconds=500,
        maximum_queue_seconds=30,
    )
    assert stage_sequence_feasible_parallel(
        stages,
        remaining_seconds=500,
        maximum_queue_seconds=30,
        worker_count=3,
    )


def test_progress_gate_reports_obligation_and_evidence_delta():
    tracker = AgentProgressTracker()
    first = tracker.observe(
        "solver-1",
        _payload(action="continue_reasoning", obligations=["ob-1"], evidence=[]),
    )
    second = tracker.observe(
        "solver-1",
        _payload(
            action="continue_reasoning",
            obligations=["ob-1", "ob-2"],
            evidence=["ev-1"],
        ),
    )

    assert first.obligation_delta == 1
    assert first.evidence_delta == 0
    assert second.obligation_delta == 1
    assert second.evidence_delta == 1
    assert second.information_gain >= 2
    assert second.continue_allowed
