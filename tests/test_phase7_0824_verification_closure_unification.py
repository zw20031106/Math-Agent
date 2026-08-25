from __future__ import annotations

from mathforge.harness.schemas import CandidateSolution, Claim, EvidenceRecord, MethodStep, ProofObligation
from mathforge.runtime_flows.final_flow import FinalProofStatusService
from mathforge.verification.arbitration import ArbitrationPolicy
from mathforge.verification.capabilities import VerificationCapability
from mathforge.verification.completion import ProofCompletionGate
from mathforge.verification.evidence import ClaimEvidenceVerifier, EvidenceLedger
from mathforge.verification.verification_closure import AuditRecord
from mathforge.verification.verification_v2 import assess_verification
from mathforge.tools.executor import ToolExecutor


def _candidate(
    candidate_id: str = "c",
    *,
    version: int = 1,
    steps: list[str] | None = None,
    parse_tier: str = "strict",
    degraded: bool = False,
) -> CandidateSolution:
    claims = [
        Claim(
            "conclusion",
            "The conclusion follows.",
            check_type="sufficiency",
            importance="critical",
        )
    ]
    return CandidateSolution(
        candidate_id,
        "PrimarySolver",
        "direct-deduction",
        "QED",
        "text",
        claims=claims,
        public_solution_steps=steps or ["Establish the conclusion."],
        method_steps=[MethodStep("step-1", "conclusion", ["conclusion"])],
        version=version,
        parse_tier=parse_tier,
        degraded=degraded,
    )


def _obligation(candidate_id: str = "c") -> ProofObligation:
    return ProofObligation(
        f"{candidate_id}:sufficiency",
        "sufficiency",
        "establish the conclusion",
        source_claim_ids=["conclusion"],
    )


def _hard_support(candidate_id: str = "c", evidence_id: str = "ev-1") -> EvidenceRecord:
    obligation = _obligation(candidate_id)
    return EvidenceRecord(
        evidence_id,
        candidate_id,
        "conclusion",
        "offline:proof_checker",
        "pass",
        "hard",
        "deterministic obligation support",
        {"obligation_ids": [obligation.obligation_id]},
        {"schema_valid": True, "formal_engine": False},
        VerificationCapability.PROOF_OBLIGATION_REVIEW.value,
    )


def test_unsupported_reasoning_is_explicit_unknown_evidence():
    candidate = CandidateSolution(
        "reasoning",
        "PrimarySolver",
        "direct-deduction",
        "2",
        "integer",
        claims=[Claim("step", "Add the two units.", check_type="reasoning")],
    )
    records = ClaimEvidenceVerifier(ToolExecutor()).verify(candidate, EvidenceLedger())
    assert [(item.claim_id, item.status) for item in records] == [("step", "unknown")]
    assert records[0].evidence_type == "host:check_type_resolution"


def test_final_audit_recomputes_the_same_terminal_closure():
    candidate = _candidate(steps=["Establish the conclusion.", "Therefore QED."])
    obligation = _obligation()
    evidence = [_hard_support()]
    audit = AuditRecord(
        "audit-1",
        "turn-1",
        candidate.candidate_id,
        candidate.version,
        "complete_audited",
        (),
        (),
        reviewed_artifact_ids=("artifact-1",),
        requested_action="accept",
        public_rationale="All closure items are covered.",
        stop_reason="complete",
        reviewed_obligation_ids=(obligation.obligation_id,),
        required_obligation_ids=(obligation.obligation_id,),
        required_artifact_ids=("artifact-1",),
    )
    decision = ProofCompletionGate().evaluate(
        candidate,
        evidence,
        [obligation],
        audits=[audit],
    )
    final = FinalProofStatusService().finalize(
        candidate,
        decision,
        obligations=[obligation],
        audits=[audit],
        evidence=evidence,
        closure=decision.verification_closure,
    )
    assert decision.status == "complete_audited"
    assert decision.verification_closure.audit_id == "audit-1"
    assert decision.verification_closure.terminal_closure is True
    assert final.status == "complete_audited"
    assert final.assurance_level == "audited"
    assert final.terminal_closure is True


def test_proof_full_without_mapped_derivation_cannot_complete():
    candidate = _candidate(steps=["QED", "QED"])
    obligation = _obligation()
    decision = ProofCompletionGate().evaluate(
        candidate,
        [_hard_support()],
        [obligation],
        response_mode="proof_full",
    )
    assert decision.status == "incomplete"
    assert decision.terminal_closure is False
    assert decision.verification_closure.derivation_quality != "complete"


def test_arbitration_exposes_targeted_check_for_semantic_tie():
    first = _candidate("first", steps=["Derive the result."])
    second = _candidate("second", steps=["Derive the result."])
    result = ArbitrationPolicy().select([first, second], [], {})
    assert result.targeted_check_required is True
    assert result.tie_break_reason == "targeted_check_required"
    assert result.selected.candidate_id in {"first", "second"}


def test_rolled_back_repair_transaction_cannot_be_terminal():
    candidate = _candidate(version=2, steps=["Establish the conclusion.", "Therefore QED."])
    closure = assess_verification(
        candidate,
        [_hard_support()],
        [_obligation()],
        repaired=True,
        repair_lineage=[
            {
                "proposed_candidate_id": candidate.candidate_id,
                "transaction_status": "rolled_back",
            }
        ],
    )
    assert closure.completion_status == "failed"
    assert closure.terminal_closure is False
    assert "repair_transaction_inactive" in closure.reasons
