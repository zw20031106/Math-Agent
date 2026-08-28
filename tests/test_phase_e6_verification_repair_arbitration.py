from __future__ import annotations

import pytest

from mathforge.harness.schemas import CandidateSolution, Claim, EvidenceRecord
from mathforge.tools.registry import ToolResult
from mathforge.verification.arbitration import ArbitrationPolicy
from mathforge.verification.candidate_pool import CandidatePool
from mathforge.verification.e6 import (
    AtomicRepairClosure,
    CompletionPolicy,
    EvidenceStatus,
    FinalAuditCoverage,
    RepairErrorCategory,
    VerificationState,
    assess_answer_consistency,
    evidence_status,
    final_audit_coverage,
    normalize_evidence_status,
)
from mathforge.verification.review_repair_audit_v2 import (
    classify_concession,
    classify_repair_finding,
)
from mathforge.verification.verification_closure import AuditRecord, CritiqueFinding


def _candidate(
    candidate_id: str,
    answer: str = "4",
    *,
    method: str = "direct-deduction",
    model_identity: str = "",
) -> CandidateSolution:
    candidate = CandidateSolution(
        candidate_id,
        "PrimarySolver",
        method,
        answer,
        "integer",
        claims=[Claim(f"{candidate_id}:claim", f"x = {answer}", importance="critical")],
        public_solution_steps=[f"x = {answer}"],
        model_identity=model_identity,
    )
    candidate.validate()
    return candidate


def test_verification_state_keeps_not_disproved_separate_from_hard_verified():
    state = VerificationState(True, True, True, False, False, False)
    assert state.not_disproved is True
    assert state.hard_verified is False
    with pytest.raises(ValueError, match="semantic support"):
        VerificationState(True, True, True, False, True, False)


def test_answer_only_low_policy_requires_independent_or_real_support():
    state = VerificationState(True, True, True, False, False, False)
    policy = CompletionPolicy.for_context("answer_only", "low")
    denied = policy.evaluate(state)
    allowed = policy.evaluate(state, independent_agreement=True)
    assert denied.allowed is False
    assert "independent_agreement_or_support_missing" in denied.reasons
    assert allowed.allowed is True


def test_answer_consistency_checks_terminal_formatter_and_scorer_edges():
    candidate = _candidate("candidate", "2")
    mismatch = assess_answer_consistency(
        candidate,
        terminal_claim="x = 3",
        formatter_output="2",
        scorer_normalized_answer="3",
    )
    assert mismatch.consistent is False
    assert "terminal_claim" in mismatch.mismatches
    assert "scorer_normalization" in mismatch.mismatches

    consistent = assess_answer_consistency(
        candidate,
        terminal_claim="x = 2",
        formatter_output="Final answer: 2",
        scorer_normalized_answer="2",
    )
    assert consistent.consistent is True
    assert consistent.fully_checked is True


def test_same_model_is_correlated_even_with_different_prompt_and_method():
    pool = CandidatePool()
    first = _candidate("first", method="direct-deduction")
    second = _candidate("second", method="structural-transform")
    base = {
        "model_identity": "same-model",
        "prompt_hash": "prompt-a",
        "shared_context_hash": "shared-a",
        "branch_context_hash": "branch-a",
        "private_context_hash": "private-a",
        "method_family": "direct-deduction",
    }
    pool.submit(
        first,
        author_agent_id="agent-a",
        source_turn_id="turn-a",
        candidate_artifact_id="artifact-a",
        provenance=base,
    )
    entry = pool.submit(
        second,
        author_agent_id="agent-b",
        source_turn_id="turn-b",
        candidate_artifact_id="artifact-b",
        provenance={
            **base,
            "prompt_hash": "prompt-b",
            "branch_context_hash": "branch-b",
            "private_context_hash": "private-b",
            "method_family": "structural-transform",
        },
    )
    assert entry.independent is False
    assert entry.model_independence is False
    assert entry.correlated_corroboration is True


def test_different_model_and_low_correlated_context_can_corroborate():
    pool = CandidatePool()
    first = _candidate("first", method="direct-deduction")
    second = _candidate("second", method="structural-transform")
    first_provenance = {
        "model_identity": "model-a",
        "prompt_hash": "prompt-a",
        "shared_context_hash": "shared-a",
        "branch_context_hash": "branch-a",
        "private_context_hash": "private-a",
        "method_family": "direct-deduction",
    }
    pool.submit(
        first,
        author_agent_id="agent-a",
        source_turn_id="turn-a",
        candidate_artifact_id="artifact-a",
        provenance=first_provenance,
    )
    entry = pool.submit(
        second,
        author_agent_id="agent-b",
        source_turn_id="turn-b",
        candidate_artifact_id="artifact-b",
        provenance={
            **first_provenance,
            "model_identity": "model-b",
            "prompt_hash": "prompt-b",
            "shared_context_hash": "shared-b",
            "branch_context_hash": "branch-b",
            "private_context_hash": "private-b",
            "method_family": "structural-transform",
        },
    )
    assert entry.independent is True
    assert entry.model_independence is True


def test_concession_does_not_reject_without_confirmed_global_criticality():
    assert classify_concession("warning").candidate_status == "challenged"
    critical = classify_concession("critical", scope="global", confirmed=False)
    assert critical.candidate_status == "repair_requested"
    assert critical.requires_independent_confirmation is True
    assert classify_concession(
        "critical", scope="global", confirmed=True
    ).candidate_status == "rejected"


def test_repair_error_classifier_exposes_e6_categories_and_actions():
    finding = CritiqueFinding(
        "finding",
        "candidate",
        "claim",
        (),
        (),
        "fail",
        "local",
        "local_repair",
        "The representation encoding is malformed.",
        "",
        "",
    )
    directive = classify_repair_finding(finding)
    assert directive.error_class == RepairErrorCategory.REPRESENTATION.value
    assert directive.action == "re_encode"


def test_atomic_repair_closure_requires_all_three_model_stages_and_reserve():
    admitted = AtomicRepairClosure.admit(
        repair_p95_seconds=2,
        reverify_p95_seconds=3,
        final_audit_p95_seconds=4,
        finalize_reserve_seconds=1,
        remaining_seconds=11,
        remaining_calls=3,
    )
    denied = AtomicRepairClosure.admit(
        repair_p95_seconds=2,
        reverify_p95_seconds=3,
        final_audit_p95_seconds=4,
        finalize_reserve_seconds=1,
        remaining_seconds=9,
        remaining_calls=3,
    )
    assert admitted.admitted is True
    assert admitted.required_seconds == 10.0
    assert denied.admitted is False
    assert denied.candidate_retained is True
    assert denied.best_available is True


def test_final_audit_coverage_requires_version_and_empty_open_items():
    audit = AuditRecord(
        "audit",
        "turn",
        "candidate",
        2,
        "complete_audited",
        (),
        (),
        ("artifact",),
        "retain",
        "checked",
        "done",
        reviewed_finding_ids=("finding",),
        reviewed_obligation_ids=("obligation",),
        required_artifact_ids=("artifact",),
        required_finding_ids=("finding",),
        required_obligation_ids=("obligation",),
    )
    coverage = final_audit_coverage(audit, active_candidate_version=2)
    assert coverage.complete is True
    assert final_audit_coverage(audit, active_candidate_version=3).complete is False
    assert isinstance(coverage, FinalAuditCoverage)


def test_evidence_taxonomy_only_passes_real_capability_matched_hard_records():
    assert normalize_evidence_status("timed_out") is EvidenceStatus.TIMEOUT
    assert evidence_status("parse_error") == "MALFORMED"
    result = ToolResult(
        "symbolic_equivalence",
        "pass",
        "hard",
        "equivalent",
        {"answer": "4"},
        capability="equality.symbolic_under_domain",
    )
    record = EvidenceRecord(
        "evidence",
        "candidate",
        "claim",
        "tool:symbolic_equivalence",
        result.status,
        result.strength,
        result.summary,
        payload=result.payload,
        invocation={"schema_valid": True},
        capability=result.capability,
    )
    from mathforge.verification.e6 import is_real_hard_pass

    assert is_real_hard_pass(record) is True
