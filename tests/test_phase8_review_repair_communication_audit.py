from __future__ import annotations

import pytest

from mathforge.agent_runtime.artifact_store import SessionArtifactStore
from mathforge.agent_runtime.definitions import AgentRegistry
from mathforge.agent_runtime.mailbox import SessionMailbox
from mathforge.agent_runtime.state import (
    AgentInstance,
    AgentStateRegistry,
    AgentTaskRegistry,
)
from mathforge.harness.schemas import CandidateSolution, Claim, ProofObligation
from mathforge.verification.candidate_pool import CandidatePool
from mathforge.verification.review_repair_audit_v2 import (
    REPAIR_ACTION_BY_CATEGORY,
    classify_concession,
    classify_repair_finding,
    decide_bidirectional_review,
)
from mathforge.verification.verification_closure import (
    AuditRecord,
    CritiqueFinding,
    CritiqueRecord,
)


def _candidate(
    candidate_id: str,
    role: str,
    *,
    method: str = "direct",
    answer: str = "4",
    version: int = 1,
) -> CandidateSolution:
    return CandidateSolution(
        candidate_id,
        role,
        method,
        answer,
        "expression",
        claims=[Claim("claim-1", f"{method} establishes {answer}", importance="critical")],
        public_solution_steps=[f"Apply {method}."],
        version=version,
        planned_method_family=method,
        source=("llm_primary" if role == "PrimarySolver" else "llm_alternative"),
    )


def test_message_consumption_receipt_matches_named_recipient_and_turn_inputs():
    session_id = "8" * 32
    definitions = AgentRegistry.default()
    agents = AgentStateRegistry(session_id, definitions)
    primary = AgentInstance(
        f"{session_id}:PrimarySolver:solve:1",
        session_id,
        "PrimarySolver",
        "solve",
        "primary",
    )
    verifier = AgentInstance(
        f"{session_id}:VerifierSkeptic:cross_exam:1",
        session_id,
        "VerifierSkeptic",
        "cross_exam",
        "verifier",
    )
    agents.create(primary)
    agents.create(verifier)
    tasks = AgentTaskRegistry(session_id, agents, definitions)
    task = tasks.create("solve_primary", primary.agent_id)
    artifacts = SessionArtifactStore(session_id, agents, definitions)
    artifact = artifacts.publish(
        artifact_type="CandidateArtifact",
        producer_agent_id=primary.agent_id,
        task_id=task.task_id,
        turn_id="turn-producer",
        payload={"candidate_id": "c"},
    )
    mailbox = SessionMailbox(session_id, agents, tasks, artifacts, definitions)
    thread = mailbox.create_thread((primary.agent_id, verifier.agent_id))
    message = mailbox.send(
        thread_id=thread.thread_id,
        sender_agent_id=primary.agent_id,
        recipient_agent_id=verifier.agent_id,
        task_id=task.task_id,
        message_type="candidate_published",
        artifact_ids=(artifact.artifact_id,),
        public_summary="Candidate ready for verification.",
    )

    assert not mailbox.consume_for_turn(
        consumer_agent_id=primary.agent_id,
        turn_id="turn-wrong",
        input_artifact_ids=(artifact.artifact_id,),
    )
    receipts = mailbox.consume_for_turn(
        consumer_agent_id=verifier.agent_id,
        turn_id="turn-consumer",
        input_artifact_ids=(artifact.artifact_id,),
    )

    assert len(receipts) == 1
    assert receipts[0].message_id == message.message_id
    assert receipts[0].consumer_agent_id == message.recipient_agent_id
    assert set(receipts[0].artifact_ids) <= {artifact.artifact_id}
    assert mailbox.snapshot()["message_consumptions"][0]["turn_id"] == "turn-consumer"


def test_bidirectional_review_is_conditionally_triggered():
    left = _candidate("left", "PrimarySolver")
    duplicate = _candidate("duplicate", "AlternativeSolver")
    distinct = _candidate(
        "distinct",
        "AlternativeSolver",
        method="constructive",
    )

    skipped = decide_bidirectional_review(
        [left, duplicate],
        risk_level="medium",
        independent_candidate_ids=("left", "duplicate"),
    )
    triggered = decide_bidirectional_review(
        [left, distinct],
        risk_level="medium",
        independent_candidate_ids=("left", "distinct"),
    )

    assert not skipped.should_run
    assert triggered.should_run and triggered.bidirectional
    assert "method_diversity" in triggered.reason_codes


def test_warning_concession_is_retained_but_confirmed_global_critical_rejects():
    pool = CandidatePool()
    candidate = _candidate("candidate", "PrimarySolver")
    pool.submit(
        candidate,
        author_agent_id="agent-primary",
        source_turn_id="turn-1",
        candidate_artifact_id="artifact-1",
    )

    warning = pool.attach_rebuttal(
        candidate.candidate_id,
        "rebuttal-warning",
        conceded_finding_ids=("warning-1",),
        finding_severities={"warning-1": "warning"},
    )

    assert warning.status == "challenged"
    assert warning.status != "rejected"
    assert classify_concession(
        "critical",
        scope="global",
        confirmed=True,
    ).candidate_status == "rejected"


def test_global_failure_selects_new_branch_and_repair_taxonomy_is_complete():
    finding = CritiqueFinding(
        "finding-global",
        "candidate",
        "",
        (),
        (),
        "fail",
        "global",
        "new_branch",
        "The method cannot satisfy the target.",
        "",
        "A counterexample invalidates the method.",
    )
    critique = CritiqueRecord(
        "critique-1",
        "turn-verifier",
        (finding,),
        (),
        (),
        "new_branch",
        "global_method_failed",
    )

    directive = classify_repair_finding(finding)
    assert critique.requires_new_branch
    assert directive.category == "global_method"
    assert directive.action == "new_branch"
    assert set(REPAIR_ACTION_BY_CATEGORY) == {
        "local_arithmetic",
        "local_theorem_condition",
        "representation_format",
        "global_method",
        "problem_interpretation",
    }


def test_complete_audit_enforces_required_coverage_and_rejects_stale_version():
    candidate = _candidate("candidate", "PrimarySolver", version=2)
    obligation = ProofObligation(
        "obligation-1",
        "sufficiency",
        "Check sufficiency.",
        source_claim_ids=["claim-1"],
    )
    base_payload = {
        "candidate_id": candidate.candidate_id,
        "candidate_version": candidate.version,
        "status": "complete_audited",
        "open_finding_ids": [],
        "open_obligation_ids": [],
        "reviewed_artifact_ids": ["artifact-candidate"],
        "reviewed_finding_ids": [],
        "reviewed_obligation_ids": [obligation.obligation_id],
        "requested_action": "retain",
        "public_rationale": "Every required audit target was checked.",
        "stop_reason": "audit_complete",
    }

    with pytest.raises(ValueError, match="does not cover every required item"):
        AuditRecord.from_model_payload(
            {**base_payload, "reviewed_obligation_ids": []},
            audit_id="audit-missing",
            source_turn_id="turn-audit",
            candidate=candidate,
            valid_finding_ids=set(),
            valid_obligation_ids={obligation.obligation_id},
            allowed_artifact_ids={"artifact-candidate"},
            required_obligation_ids={obligation.obligation_id},
            required_artifact_ids={"artifact-candidate"},
        )

    audit = AuditRecord.from_model_payload(
        base_payload,
        audit_id="audit-complete",
        source_turn_id="turn-audit",
        candidate=candidate,
        valid_finding_ids=set(),
        valid_obligation_ids={obligation.obligation_id},
        allowed_artifact_ids={"artifact-candidate"},
        required_obligation_ids={obligation.obligation_id},
        required_artifact_ids={"artifact-candidate"},
    )
    assert audit.complete and audit.coverage_complete

    with pytest.raises(ValueError, match="version"):
        AuditRecord.from_model_payload(
            {**base_payload, "candidate_version": 1},
            audit_id="audit-stale",
            source_turn_id="turn-audit",
            candidate=candidate,
            valid_finding_ids=set(),
            valid_obligation_ids={obligation.obligation_id},
            allowed_artifact_ids={"artifact-candidate"},
        )
