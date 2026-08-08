from __future__ import annotations

from pathlib import Path

from mathforge.harness.schemas import (
    CandidateSolution,
    Claim,
    EvidenceRecord,
    ProofObligation,
)
from mathforge.runtime_flows import (
    AgentEventProjector,
    FinalProofStatusService,
    PublicContractGuard,
)
from mathforge.verification.capabilities import VerificationCapability
from mathforge.verification.completion import ProofCompletionGate
from mathforge.verification.verification_closure import AuditRecord


ROOT = Path(__file__).resolve().parents[1]


def _candidate(*, version: int = 1, steps: int = 2) -> CandidateSolution:
    return CandidateSolution(
        "proof-1",
        "PrimarySolver",
        "direct-deduction",
        "QED",
        "text",
        claims=[Claim("claim-1", "The conclusion follows.")],
        public_solution_steps=[f"Public step {index}." for index in range(steps)],
        solution_text="A public proof.",
        version=version,
    )


def _obligation() -> ProofObligation:
    return ProofObligation(
        "proof-1:sufficiency",
        "sufficiency",
        "establish the conclusion",
        source_claim_ids=["claim-1"],
    )


def _soft_review(obligation: ProofObligation) -> EvidenceRecord:
    return EvidenceRecord(
        "review-1",
        "proof-1",
        "claim-1",
        "llm:VerifierSkeptic",
        "pass",
        "soft",
        "reviewed",
        {"obligation_ids": [obligation.obligation_id]},
        {"role": "VerifierSkeptic"},
        VerificationCapability.PROOF_OBLIGATION_REVIEW.value,
    )


def test_proof_full_missing_public_steps_cannot_complete():
    decision = ProofCompletionGate().evaluate(
        _candidate(steps=1),
        [],
        [],
        response_mode="proof_full",
    )
    assert decision.status == "incomplete"


def test_peer_review_pass_without_final_audit_remains_incomplete():
    candidate = _candidate()
    obligation = _obligation()
    decision = ProofCompletionGate().evaluate(
        candidate,
        [_soft_review(obligation)],
        [obligation],
        response_mode="proof_full",
    )
    final = FinalProofStatusService().finalize(
        candidate,
        decision,
        obligations=[obligation],
        response_mode="proof_full",
    )
    assert decision.status == "incomplete"
    assert final.status == "incomplete"


def test_hard_failure_always_finalizes_as_failed():
    candidate = _candidate()
    obligation = _obligation()
    hard_failure = EvidenceRecord(
        "hard-fail",
        candidate.candidate_id,
        "claim-1",
        "tool:symbolic",
        "fail",
        "hard",
        "counterexample found",
        invocation={
            "claim_kind": "equality",
            "schema_valid": True,
            "fatal_eligible": True,
        },
        capability=VerificationCapability.EQUALITY_SYMBOLIC_UNDER_DOMAIN.value,
    )
    decision = ProofCompletionGate().evaluate(
        candidate,
        [hard_failure],
        [obligation],
    )
    final = FinalProofStatusService().finalize(
        candidate,
        decision,
        obligations=[obligation],
    )
    assert decision.status == "failed"
    assert final.status == "failed"


def test_complete_audited_covers_every_required_obligation():
    candidate = _candidate()
    obligation = _obligation()
    decision = ProofCompletionGate().evaluate(
        candidate,
        [_soft_review(obligation)],
        [obligation],
        response_mode="proof_full",
    )
    audit = AuditRecord(
        "audit-1",
        "turn-1",
        candidate.candidate_id,
        candidate.version,
        "complete_audited",
        (),
        (),
        ("artifact-1",),
        "accept",
        "All required obligations were reviewed.",
        "audit_complete",
    )
    final = FinalProofStatusService().finalize(
        candidate,
        decision,
        obligations=[obligation],
        audits=[audit],
        response_mode="proof_full",
    )
    assert final.status == "complete_audited"
    assert final.audit_id == "audit-1"


def test_repaired_candidate_requires_version_matched_final_audit():
    candidate = _candidate(version=2)
    decision = ProofCompletionGate().evaluate(candidate, [], [])
    final = FinalProofStatusService().finalize(
        candidate,
        decision,
        repaired=True,
    )
    assert final.status == "incomplete"
    assert final.reason_code == "repaired_candidate_requires_final_audit"


def test_agent_protocol_projects_lifecycle_communication_and_repair_events():
    snapshot = {
        "agents": [
            {
                "agent_id": "agent-1",
                "role": "PrimarySolver",
                "mode": "solve",
                "descriptor": "primary-1",
                "state": {
                    "status": "completed",
                    "model_call_count": 1,
                    "failure_code": "",
                },
            }
        ],
        "tasks": [
            {
                "task_id": "task-1",
                "task_type": "solve_primary",
                "assigned_agent_id": "agent-1",
                "created_sequence": 1,
            }
        ],
        "turn_lineage": [
            {
                "turn_id": "turn-1",
                "agent_id": "agent-1",
                "task_id": "task-1",
                "artifact_id": "artifact-1",
                "status": "completed",
            }
        ],
        "artifacts": [
            {
                "artifact_id": "artifact-1",
                "artifact_type": "CandidateArtifact",
                "producer_agent_id": "agent-1",
                "task_id": "task-1",
                "turn_id": "turn-1",
                "payload": {"raw_response": "must not be projected"},
            }
        ],
        "messages": [
            {
                "message_id": "message-1",
                "thread_id": "thread-1",
                "sender_agent_id": "agent-1",
                "recipient_agent_id": "agent-2",
                "message_type": "candidate_published",
                "artifact_ids": ["artifact-1"],
                "public_summary": "Candidate ready for review.",
                "sequence": 1,
            }
        ],
    }
    events = AgentEventProjector().project(
        snapshot,
        repair_lineage=[
            {
                "source_candidate_id": "proof-1",
                "proposed_candidate_id": "proof-1-v2",
                "rolled_back": False,
            },
            {
                "source_candidate_id": "proof-2",
                "proposed_candidate_id": "proof-2-v2",
                "rolled_back": True,
            },
        ],
    )
    names = {name for name, _ in events}
    assert {
        "agent_created",
        "task_assigned",
        "model_turn_started",
        "model_turn_completed",
        "artifact_published",
        "message_sent",
        "message_delivered",
        "repair_committed",
        "repair_rolled_back",
        "agent_stopped",
    } <= names
    assert all("payload" not in details for _, details in events)


def test_fixed_round_and_stage_allocation_implementations_are_removed():
    runtime_source = (ROOT / "mathforge" / "runtime.py").read_text(encoding="utf-8")
    reasoning_source = (
        ROOT / "mathforge" / "harness" / "reasoning_state.py"
    ).read_text(encoding="utf-8")
    assert "planned_rounds" not in runtime_source + reasoning_source
    assert not (ROOT / "mathforge" / "harness" / "allocation.py").exists()


def test_formal_entry_contract_guard_keeps_answer_and_trace_serializable():
    result = PublicContractGuard.normalize(
        {"final_response": "", "trace": None},
        "Fallback answer.",
    )
    assert result["final_response"] == "Fallback answer."
    assert result["trace"] == []
