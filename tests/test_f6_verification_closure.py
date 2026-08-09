from __future__ import annotations

import json

import pytest

from mathforge.config import HarnessConfig
from mathforge.harness.schemas import CandidateSolution, Claim
from mathforge.runtime import MathForgeHarness
from mathforge.verification.peer_review import PeerReviewRecord, ReviewFinding
from mathforge.verification.verification_closure import CritiqueRecord
from tests.fake_client import FakeClient, _agent_envelope


def _config(**overrides) -> HarnessConfig:
    values = {
        "profile": "f6-test",
        "status": "test",
        "primary_max_tokens": 65_536,
        "max_model_calls": 30,
        "model_call_policy": "adaptive_bounded",
        "max_logical_model_calls_per_problem": 30,
        "soft_call_checkpoints": (8, 14, 22),
        "speculative_exploration_cutoff": 22,
        "closure_reserve_calls": 8,
        "enable_router": True,
        "enable_skills": False,
        "enable_alternatives": True,
        "enable_tools": True,
        "enable_evidence": True,
        "enable_proof_obligations": True,
        "enable_peer_cross_review": True,
        "enable_verification_closure": True,
        "enable_verifier": True,
        "enable_memory": False,
        "enable_lemma_loop": False,
        "enable_rag": False,
        "enable_repair": True,
        "enable_finalizer": False,
        "enable_shadow": False,
        "enable_frozen_lemma_store": False,
        "enable_long_horizon": True,
    }
    values.update(overrides)
    return HarnessConfig(**values)


def _event(result: dict, name: str) -> dict:
    return next(item for item in result["trace"] if item["event"] == name)


def test_cross_exam_and_final_audit_are_distinct_model_agents_with_artifacts():
    result = MathForgeHarness(FakeClient(), _config()).solve(
        "Prove that x equals x.",
        {},
    )
    verifier = _event(result, "verifier_completed")
    audit = _event(result, "final_audit_completed")
    decision = _event(result, "decision_committed")
    protocol = _event(result, "agent_protocol")
    calls = _event(result, "budget_summary")["model_call_records"]
    verifier_calls = [item for item in calls if item["agent_role"] == "VerifierSkeptic"]

    assert verifier["critique_id"]
    assert verifier["critique_artifact_id"]
    assert verifier["peer_review_assessment_count"] == 2
    assert verifier["independent_model_call"] is True
    assert audit["status"] == "complete_audited"
    assert audit["candidate_scope_count"] == 1
    assert audit["verifier_instance_distinct_from_cross_exam"] is True
    assert {item["agent_mode"] for item in verifier_calls} == {
        "cross_exam",
        "final_audit",
    }
    assert len({item["agent_id"] for item in verifier_calls}) == 2
    artifacts = protocol["artifacts"]
    critiques = [item for item in artifacts if item["artifact_type"] == "CritiqueArtifact"]
    audits = [item for item in artifacts if item["artifact_type"] == "AuditArtifact"]
    decisions = [item for item in artifacts if item["artifact_type"] == "DecisionArtifact"]
    assert len(critiques) == len(audits) == 1
    assert len(decisions) == 1
    assert critiques[0]["payload"]["result_payload"]["peer_review_assessments"]
    assert audits[0]["payload"]["result_payload"]["candidate_id"] == audit["candidate_id"]
    assert decisions[0]["artifact_id"] == decision["decision_artifact_id"]
    assert decisions[0]["producer_kind"] == "deterministic_service"
    assert decisions[0]["producer_service_id"] == "DeterministicArbitrator"
    assert audits[0]["artifact_id"] in decisions[0]["parent_artifact_ids"]
    event_names = {item["event"] for item in result["trace"]}
    assert {
        "agent_created",
        "task_assigned",
        "model_turn_started",
        "model_turn_completed",
        "artifact_published",
        "message_sent",
        "message_delivered",
        "peer_review_completed",
        "rebuttal_completed",
        "verifier_completed",
        "final_audit_completed",
        "decision_committed",
        "agent_stopped",
    } <= event_names


def test_final_audit_only_reviews_the_candidate_selected_for_commit():
    client = FakeClient()
    result = MathForgeHarness(client, _config()).solve("Compute 2+2.", {})
    audit = _event(result, "final_audit_completed")
    decision = _event(result, "candidate_arbitrated")
    audit_request = next(
        json.loads(call["messages"][-1]["content"])
        for call in client.calls
        if "Public protocol mode is final_audit"
        in call["messages"][0]["content"]
    )

    assert audit["candidate_id"] == decision["selected"]
    assert audit["candidate_scope_count"] == 1
    assert audit["open_finding_ids"] == []
    assert audit["open_obligation_ids"] == []
    assert all(
        finding["candidate_id"] == audit["candidate_id"]
        for critique in audit_request["critiques"]
        for finding in critique["findings"]
    )
    assert all(
        review["candidate_id"] == audit["candidate_id"]
        for review in audit_request["peer_reviews"]
    )
    assert all(
        rebuttal["candidate_id"] == audit["candidate_id"]
        for rebuttal in audit_request["rebuttals"]
    )


def test_global_failure_cannot_be_disguised_as_local_repair():
    candidate = CandidateSolution(
        "candidate",
        "PrimarySolver",
        "direct",
        "QED",
        "text",
        claims=[Claim("c1", "The conclusion follows.")],
    )
    peer = PeerReviewRecord(
        "review-1",
        "reviewer",
        "author",
        "candidate",
        1,
        "candidate-artifact",
        "turn-1",
        (
            ReviewFinding(
                "peer-f1",
                "candidate",
                "c1",
                "",
                (),
                "unknown",
                "The method may omit a case.",
                "",
                "",
                "warning",
            ),
        ),
        "unknown",
        "distinct",
        (),
        (),
        (),
        "review",
        "complete",
    )
    payload = {
        "findings": [
            {
                "finding_id": "vf-1",
                "candidate_id": "candidate",
                "claim_id": "c1",
                "obligation_ids": [],
                "peer_finding_ids": ["peer-f1"],
                "status": "fail",
                "scope": "global",
                "actionability": "local_repair",
                "public_rationale": "The core method is invalid.",
                "missing_condition": "",
                "counterexample_summary": "A global counterexample exists.",
            }
        ],
        "peer_review_assessments": [
            {
                "finding_id": "peer-f1",
                "status": "pass",
                "public_rationale": "The peer concern is valid.",
            }
        ],
        "uncovered_goal_ids": [],
        "recommended_action": "new_branch",
        "stop_reason": "core_method_failed",
    }

    with pytest.raises(ValueError, match="Global failure"):
        CritiqueRecord.from_model_payload(
            payload,
            critique_id="critique-1",
            source_turn_id="turn-2",
            candidates=[candidate],
            obligations={},
            peer_reviews=[peer],
        )

    payload["findings"][0]["actionability"] = "new_branch"
    payload["peer_review_assessments"][0]["status"] = "fail"
    critique = CritiqueRecord.from_model_payload(
        payload,
        critique_id="critique-2",
        source_turn_id="turn-3",
        candidates=[candidate],
        obligations={},
        peer_reviews=[peer],
    )
    assert critique.peer_review_assessments[0].status == "fail"


class _LocalRepairClient(FakeClient):
    def __init__(self) -> None:
        super().__init__()
        self.cross_exams = 0

    def chat(self, *, messages, temperature, max_tokens) -> str:
        system = messages[0]["content"]
        if system.startswith("You are VerifierSkeptic") and (
            "Public protocol mode is cross_exam" in system
        ):
            self.cross_exams += 1
            if self.cross_exams == 1:
                request = json.loads(messages[-1]["content"])
                peer_findings = [
                    finding
                    for review in request["peer_reviews"]
                    for finding in review["finding_items"]
                ]
                findings = []
                for index, candidate in enumerate(request["candidates"], start=1):
                    failed = index == 1
                    findings.append(
                        {
                            "finding_id": f"local-{index}",
                            "candidate_id": candidate["candidate_id"],
                            "claim_id": candidate["claims"][0]["claim_id"],
                            "obligation_ids": [],
                            "peer_finding_ids": [
                                item.get("finding_ref", item["finding_id"])
                                for item in peer_findings
                                if item["candidate_id"] == candidate["candidate_id"]
                            ],
                            "status": "fail" if failed else "pass",
                            "scope": "local",
                            "actionability": "local_repair" if failed else "retain",
                            "public_rationale": (
                                "The cited Claim needs a claim-local correction."
                                if failed
                                else "The cited Claim remains supported."
                            ),
                            "missing_condition": "state the local equality" if failed else "",
                            "counterexample_summary": "",
                        }
                    )
                return json.dumps(
                    _agent_envelope(
                        task_result_type="CritiqueArtifact",
                        action="challenge_candidate",
                        result_payload={
                            "findings": findings,
                            "peer_review_assessments": [
                                {
                                    "finding_id": item.get(
                                        "finding_ref", item["finding_id"]
                                    ),
                                    "status": "pass",
                                    "public_rationale": "The peer Finding cites a real Claim.",
                                }
                                for item in peer_findings
                            ],
                            "uncovered_goal_ids": [],
                            "recommended_action": "local_repair",
                            "stop_reason": "claim_local_failure",
                        },
                        progress_summary="One claim-local failure was identified.",
                        stop_reason="claim_local_failure",
                    )
                )
        if system.startswith("You are RepairAgent"):
            return json.dumps(
                {
                    "replacement_claims": [
                        {
                            "claim_id": "c1",
                            "statement": "The requested local equality follows directly.",
                            "depends_on": [],
                            "check_type": "reasoning",
                            "importance": "critical",
                        }
                    ],
                    "public_solution_steps": [
                        "Apply the stated equality locally and retain the conclusion."
                    ],
                    "final_answer": "Prove that x equals x.",
                    "unresolved_obligations": [],
                }
            )
        return super().chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )


def test_local_repair_is_model_authored_critique_linked_and_reverified():
    result = MathForgeHarness(_LocalRepairClient(), _config()).solve(
        "Prove that x equals x.",
        {},
    )
    repair = _event(result, "repair_completed")
    protocol = _event(result, "agent_protocol")
    calls = _event(result, "budget_summary")["model_call_records"]
    repair_calls = [item for item in calls if item["agent_role"] == "RepairAgent"]
    repair_artifact = next(
        item
        for item in protocol["artifacts"]
        if item["artifact_id"] == repair["repair_artifact_id"]
    )

    assert len(repair_calls) == 1
    assert repair["critique_id"]
    assert repair["critique_artifact_id"]
    assert repair["affected_claim_ids"] == ["c1"]
    assert repair["reverified_claim_ids"]
    assert repair_artifact["artifact_type"] == "RepairPatchArtifact"
    assert repair_artifact["producer_agent_id"] == repair_calls[0]["agent_id"]
    assert repair["critique_artifact_id"] in repair_artifact["parent_artifact_ids"]
    if repair["rolled_back"]:
        assert _event(result, "candidate_arbitrated")["selected"] != repair.get(
            "proposed_candidate_id"
        )


class _NewBranchClient(FakeClient):
    def __init__(self) -> None:
        super().__init__()
        self.cross_exams = 0

    def chat(self, *, messages, temperature, max_tokens) -> str:
        system = messages[0]["content"]
        if system.startswith("You are VerifierSkeptic") and (
            "Public protocol mode is cross_exam" in system
        ):
            self.cross_exams += 1
            if self.cross_exams == 1:
                request = json.loads(messages[-1]["content"])
                candidate = request["candidates"][0]
                peer_findings = [
                    finding
                    for review in request["peer_reviews"]
                    for finding in review["finding_items"]
                ]
                return json.dumps(
                    _agent_envelope(
                        task_result_type="CritiqueArtifact",
                        action="challenge_candidate",
                        result_payload={
                            "findings": [
                                {
                                    "finding_id": "global-failure",
                                    "candidate_id": candidate["candidate_id"],
                                    "claim_id": candidate["claims"][0]["claim_id"],
                                    "obligation_ids": [],
                                    "peer_finding_ids": [
                                        item.get("finding_ref", item["finding_id"])
                                        for item in peer_findings
                                        if item["candidate_id"] == candidate["candidate_id"]
                                    ],
                                    "status": "fail",
                                    "scope": "global",
                                    "actionability": "new_branch",
                                    "public_rationale": "The core method must be replaced.",
                                    "missing_condition": "",
                                    "counterexample_summary": "The route fails globally.",
                                }
                            ],
                            "peer_review_assessments": [
                                {
                                    "finding_id": item.get(
                                        "finding_ref",
                                        item["finding_id"],
                                    ),
                                    "status": "pass",
                                    "public_rationale": "The Peer Finding is well formed.",
                                }
                                for item in peer_findings
                            ],
                            "uncovered_goal_ids": ["core-method"],
                            "recommended_action": "new_branch",
                            "stop_reason": "global_method_failure",
                        },
                        progress_summary="A new method branch is required.",
                        stop_reason="global_method_failure",
                    )
                )
        if (
            system.startswith("You are AlternativeSolver")
            and "Required core method family: constructive-computation."
            in messages[-1]["content"]
            and "AgentTurnPayload 1.0" in system
        ):
            return json.dumps(
                _agent_envelope(
                    task_result_type="CandidateArtifact",
                    action="publish_candidate",
                    result_payload={
                        "method": "constructive-computation",
                        "final_answer": "Prove that x equals x.",
                        "public_solution_steps": [
                            "Construct the identity map.",
                            "Apply reflexivity to its image.",
                        ],
                        "claims": [
                            {
                                "claim_id": "n1",
                                "statement": "The identity map fixes $x$.",
                                "depends_on": [],
                                "check_type": "definition",
                                "importance": "supporting",
                            },
                            {
                                "claim_id": "n2",
                                "statement": "Reflexivity gives $x=x$.",
                                "depends_on": ["n1"],
                                "check_type": "reasoning",
                                "importance": "critical",
                            },
                        ],
                        "solution_text": (
                            "Construct the identity map, then apply reflexivity."
                        ),
                        "assumptions": [],
                        "theorems": [],
                        "unresolved_obligations": [],
                    },
                    progress_summary="Published a structurally new Candidate.",
                    stop_reason="candidate_complete",
                )
            )
        return super().chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )


def test_global_method_failure_creates_new_solver_branch_and_reenters_review():
    client = _NewBranchClient()
    result = MathForgeHarness(client, _config()).solve(
        "Prove that x equals x.",
        {},
    )
    branch = _event(result, "new_branch_completed")
    protocol = _event(result, "agent_protocol")
    generated = [
        item for item in result["trace"] if item["event"] == "new_branch_started"
    ]

    assert branch["status"] == "completed"
    assert branch["candidate_id"].startswith("new-branch-")
    assert branch["peer_review_reentered"] is True
    assert branch["independently_authored"] is True
    assert generated[0]["critique_artifact_id"]
    assert client.cross_exams >= 2
    new_tasks = [
        item
        for item in protocol["tasks"]
        if item["task_type"] == "solve_new_branch"
    ]
    assert len(new_tasks) == 1
    assert new_tasks[0]["method_family"]
    assert new_tasks[0]["method_family"] != "direct-deduction"
    incremental_pool = next(
        item
        for item in result["trace"]
        if item["event"] == "candidate_pool_initialized"
        and item.get("incremental") is True
    )
    assert len(incremental_pool["entries"]) == 3
    candidate_artifact = next(
        item
        for item in protocol["artifacts"]
        if item["artifact_id"] == branch["candidate_artifact_id"]
    )
    assert generated[0]["critique_artifact_id"] in candidate_artifact["parent_artifact_ids"]


class _AuditReentryClient(FakeClient):
    def __init__(self) -> None:
        super().__init__()
        self.audits = 0

    def chat(self, *, messages, temperature, max_tokens) -> str:
        system = messages[0]["content"]
        if system.startswith("You are VerifierSkeptic") and (
            "Public protocol mode is final_audit" in system
        ):
            self.audits += 1
            if self.audits == 1:
                request = json.loads(messages[-1]["content"])
                candidate = request["final_active_candidate"]
                finding_id = request["critiques"][-1]["findings"][0]["finding_id"]
                return json.dumps(
                    _agent_envelope(
                        task_result_type="AuditArtifact",
                        action="complete",
                        result_payload={
                            "candidate_id": candidate["candidate_id"],
                            "candidate_version": candidate["version"],
                            "status": "incomplete",
                            "open_finding_ids": [finding_id],
                            "open_obligation_ids": [],
                            "reviewed_artifact_ids": [],
                            "requested_action": "continue_review",
                            "public_rationale": "One normalized Finding needs another check.",
                            "stop_reason": "additional_review_required",
                        },
                        progress_summary="Audit requested another review cycle.",
                        stop_reason="additional_review_required",
                    )
                )
        return super().chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )


def test_incomplete_audit_reenters_cross_exam_then_uses_a_new_audit_instance():
    client = _AuditReentryClient()
    result = MathForgeHarness(client, _config()).solve("Prove that x equals x.", {})
    audits = [
        item for item in result["trace"] if item["event"] == "final_audit_completed"
    ]
    reentry = _event(result, "audit_reentry_decision")
    calls = _event(result, "budget_summary")["model_call_records"]
    audit_calls = [item for item in calls if item["agent_mode"] == "final_audit"]

    assert [item["status"] for item in audits] == [
        "incomplete",
        "complete_audited",
    ]
    assert reentry["reentered"] is True
    assert client.audits == 2
    assert len(audit_calls) == 2
    assert len({item["agent_id"] for item in audit_calls}) == 2


class _AuditFailureClient(FakeClient):
    def chat(self, *, messages, temperature, max_tokens) -> str:
        if "Public protocol mode is final_audit" in messages[0]["content"]:
            raise RuntimeError("simulated final audit transport failure")
        return super().chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )


def test_unavailable_final_audit_degrades_safely_without_empty_answer():
    result = MathForgeHarness(_AuditFailureClient(), _config()).solve(
        "Compute 2+2.",
        {},
    )
    audit = _event(result, "final_audit_completed")

    assert result["final_response"].strip()
    assert audit["status"] == "unavailable"
    assert audit["degraded"] is True
    assert audit["failure_code"]
