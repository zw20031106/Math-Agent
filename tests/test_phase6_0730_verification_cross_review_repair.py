from __future__ import annotations

from dataclasses import replace
import json

from mathforge.agents.verifier import VerifierSkepticAgent
from mathforge.config import HarnessConfig
from mathforge.context.views import candidate_view
from mathforge.harness.budget import CallBudget
from mathforge.harness.provider import ModelCallGate, OfficialClientProvider
from mathforge.harness.repair import ClaimRepairService
from mathforge.harness.schemas import (
    CandidatePatch,
    CandidateSolution,
    Claim,
    EvidenceRecord,
    MethodStep,
    ProofObligation,
)
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.output.judge_trace import (
    JUDGE_TRACE_SCHEMA_VERSION,
    project_judge_trace,
)
from mathforge.runtime import MathForgeHarness
from mathforge.verification.arbitration import ArbitrationPolicy
from mathforge.verification.cross_review import (
    CandidateConflictMatrix,
    CandidateReviewSummary,
    candidate_review_segments,
)
from mathforge.verification.proof_obligations import ProofObligationEngine


def _candidate(
    candidate_id: str,
    answer: str,
    *,
    claim_id: str = "conclusion",
    statement: str = "the conclusion follows",
    check_type: str = "sufficiency",
    method_kind: str = "conclusion",
) -> CandidateSolution:
    return CandidateSolution(
        candidate_id,
        "PrimarySolver",
        "direct-deduction",
        answer,
        "text",
        claims=[
            Claim(
                claim_id,
                statement,
                check_type=check_type,
                importance="critical",
            )
        ],
        public_solution_steps=[statement],
        solution_text=f"PRIVATE-{candidate_id}",
        method_steps=[
            MethodStep(
                f"step-{candidate_id}",
                method_kind,
                [claim_id],
            )
        ],
    )


def _review_record(
    candidate_id: str,
    status: str,
    target_id: str,
) -> EvidenceRecord:
    return EvidenceRecord(
        f"review-{candidate_id}",
        candidate_id,
        "conclusion",
        "llm:VerifierSkeptic",
        status,
        "soft",
        "targeted public review",
        {
            "review_target_ids": [target_id],
            "review_level": "answer",
        },
        {
            "role": "VerifierSkeptic",
            "review_target_ids": [target_id],
        },
        "proof.obligation_review",
    )


def test_problem_obligations_are_planned_before_and_bound_after_candidate():
    problem = ProblemParser().parse(
        "Prove that P holds if and only if Q, and prove the solution is unique."
    )
    engine = ProofObligationEngine()

    planned = engine.plan_problem(problem)
    candidate = _candidate(
        "primary-1",
        "QED",
        statement="Apply the named theorem and conclude.",
    )
    candidate.theorems = ["Named theorem"]
    bound = engine.generate(
        problem,
        candidate,
        problem_obligations=planned,
    )

    assert planned
    assert all(item.obligation_id.startswith("problem:") for item in planned)
    assert all(item.origin == "problem" for item in planned)
    assert {
        item.kind for item in planned
    } <= {
        item.kind for item in bound if item.origin == "problem"
    }
    assert all(
        item.obligation_id.startswith("primary-1:")
        for item in bound
    )
    assert any(
        item.kind == "theorem_preconditions"
        and item.origin == "method"
        for item in bound
    )
    assert all(item.source_claim_ids for item in bound)


def test_conflicts_create_answer_and_claim_targets_with_public_claim_segments():
    left = _candidate("left", "A", statement="critical route A")
    right = _candidate("right", "B", statement="critical route B")
    left.public_solution_steps = []
    right.public_solution_steps = []

    matrix = CandidateConflictMatrix.build(
        [
            CandidateReviewSummary.from_candidate(left),
            CandidateReviewSummary.from_candidate(right),
        ]
    )
    targets = matrix.review_targets()
    segments = candidate_review_segments(left)
    view = candidate_view(left.to_dict(), "VerifierSkeptic")

    assert matrix.conflicts[0].answer_conflict is True
    assert matrix.conflicts[0].critical_claim_conflict is True
    assert {target.level for target in targets} == {"answer", "claim"}
    assert segments == [
        {
            "segment_id": "left:claim:1",
            "claim_ids": ["conclusion"],
            "text": "critical route A",
        }
    ]
    assert view["review_segments"] == segments
    assert "solution_text" not in view
    assert "public_solution_steps" not in view


def test_verifier_skips_structurally_unreviewable_obligation_without_model_call():
    class NoCallClient:
        def chat(self, *, messages, temperature, max_tokens):
            del messages, temperature, max_tokens
            raise AssertionError("Verifier call should have been skipped")

    candidate = CandidateSolution(
        "candidate",
        "PrimarySolver",
        "direct-deduction",
        "QED",
        "text",
    )
    obligation = ProofObligation(
        "candidate:sufficiency",
        "sufficiency",
        "prove it",
    )
    result = VerifierSkepticAgent(
        OfficialClientProvider(NoCallClient(), ModelCallGate(1))
    ).review(
        ProblemParser().parse("Prove the conclusion."),
        [candidate],
        {"candidate": [obligation]},
        CallBudget(1),
        max_tokens=1024,
    )

    assert result.reason == "no_reviewable_targets"
    assert result.used_llm is False
    assert result.findings == []


def test_answer_conflict_is_targeted_and_review_level_is_host_validated():
    left = _candidate("left", "A")
    right = _candidate("right", "B")
    matrix = CandidateConflictMatrix.build(
        [
            CandidateReviewSummary.from_candidate(left),
            CandidateReviewSummary.from_candidate(right),
        ]
    )
    answer_target = next(
        target for target in matrix.review_targets()
        if target.level == "answer"
    )

    class TargetedReviewClient:
        def __init__(self) -> None:
            self.prompt = ""

        def chat(self, *, messages, temperature, max_tokens):
            del temperature, max_tokens
            self.prompt = messages[-1]["content"]
            return json.dumps(
                {
                    "findings": [
                        {
                            "candidate_id": "left",
                            "claim_id": "conclusion",
                            "obligation_ids": [],
                            "review_target_ids": [
                                answer_target.target_id
                            ],
                            "review_level": "claim",
                            "status": "pass",
                            "public_rationale": "left answer is supported",
                        }
                    ]
                }
            )

    client = TargetedReviewClient()
    result = VerifierSkepticAgent(
        OfficialClientProvider(client, ModelCallGate(1))
    ).review(
        ProblemParser().parse("Determine which conclusion holds."),
        [left, right],
        {},
        CallBudget(1),
        max_tokens=1024,
    )

    assert result.reason == "accepted"
    assert result.findings[0].review_level == "answer"
    assert result.findings[0].review_target_ids == (
        answer_target.target_id,
    )
    assert "PRIVATE-left" not in client.prompt
    assert "PRIVATE-right" not in client.prompt
    assert "review_segments" in client.prompt


def test_targeted_model_review_beats_failed_review_not_generation_order():
    left = _candidate("left", "A")
    right = _candidate("right", "B")
    target_id = "review:left:right:answer"
    evidence = [
        _review_record("left", "pass", target_id),
        _review_record("right", "fail", target_id),
    ]

    forward = ArbitrationPolicy().select(
        [right, left],
        evidence,
        {},
    )
    reverse = ArbitrationPolicy().select(
        [left, right],
        evidence,
        {},
    )
    tiers = {
        rank.candidate_id: rank.evidence_tier
        for rank in forward.ranks
    }

    assert forward.selected.candidate_id == "left"
    assert reverse.selected.candidate_id == "left"
    assert tiers == {"left": "model_review", "right": "incomplete"}


def test_independent_method_agreement_beats_uncorroborated_conflict():
    first = _candidate(
        "first",
        "7",
        statement="derive seven by algebra",
        check_type="equality",
        method_kind="transformation",
    )
    second = _candidate(
        "second",
        "7",
        claim_id="boundary",
        statement="derive seven by boundary counting",
        check_type="boundary",
        method_kind="case_split",
    )
    conflict = _candidate("conflict", "8")

    result = ArbitrationPolicy().select(
        [conflict, second, first],
        [],
        {},
    )
    agreement_matrix = CandidateConflictMatrix.build(
        [
            CandidateReviewSummary.from_candidate(first),
            CandidateReviewSummary.from_candidate(second),
        ]
    )
    tiers = {
        rank.candidate_id: rank.evidence_tier
        for rank in result.ranks
    }

    assert result.selected.candidate_id in {"first", "second"}
    assert tiers["first"] == "independent_corroboration"
    assert tiers["second"] == "independent_corroboration"
    assert tiers["conflict"] == "not_required"
    assert agreement_matrix.review_targets() == ()


def test_failed_atomic_acceptance_rolls_back_and_rejects_new_evidence():
    original = _candidate("candidate", "old")
    patch = CandidatePatch(
        source_candidate_id="candidate",
        base_version=1,
        affected_claim_ids=["conclusion"],
        replacement_claims=[
            Claim(
                "conclusion",
                "replacement conclusion",
                check_type="sufficiency",
                importance="critical",
            )
        ],
        final_answer="new",
        public_solution_steps=["replacement conclusion"],
    )
    produced: list[EvidenceRecord] = []

    def reverify(candidate, affected):
        assert affected == ["conclusion"]
        record = EvidenceRecord(
            "new-evidence",
            candidate.candidate_id,
            "conclusion",
            "llm:VerifierSkeptic",
            "pass",
            "soft",
            "reviewed",
        )
        produced.append(record)
        return [record]

    result = ClaimRepairService().attempt_for_trigger(
        original,
        [],
        ["conclusion"],
        repair=lambda *_: patch,
        reverify=reverify,
        accept=lambda *_: (False, "post_repair_not_strictly_better"),
    )

    assert result.rolled_back is True
    assert result.selected is original
    assert result.reason == "post_repair_not_strictly_better"
    assert produced[0].transaction_status == "rejected"


class _AtomicGateClient:
    def __init__(self) -> None:
        self.roles: list[str] = []

    def chat(self, *, messages, temperature, max_tokens):
        del temperature, max_tokens
        role = messages[0]["content"].split(
            "You are ",
            1,
        )[1].split(".", 1)[0]
        self.roles.append(role)
        if role == "VerifierSkeptic":
            batch = json.loads(
                messages[-1]["content"].split("Batch:\n", 1)[1]
            )
            candidate = batch["candidates"][0]
            obligation = candidate["obligations"][0]
            return json.dumps(
                {
                    "findings": [
                        {
                            "candidate_id": candidate["candidate_id"],
                            "claim_id": obligation[
                                "source_claim_ids"
                            ][0],
                            "obligation_ids": [
                                obligation["obligation_id"]
                            ],
                            "review_target_ids": [],
                            "review_level": "obligation",
                            "status": "fail",
                            "public_rationale": "a local gap remains",
                        }
                    ]
                }
            )
        if role == "RepairAgent":
            raise AssertionError(
                "Repair must not start without repair+reverify capacity"
            )
        return json.dumps(
            {
                "method": "direct-deduction",
                "method_steps": [
                    {
                        "step_id": "step-1",
                        "kind": "conclusion",
                        "claim_ids": ["conclusion"],
                        "theorem": "",
                    }
                ],
                "solution_text": "Original candidate solution.",
                "public_solution_steps": [
                    "The public conclusion follows."
                ],
                "final_answer": "QED",
                "assumptions": [],
                "theorems": [],
                "claims": [
                    {
                        "claim_id": "conclusion",
                        "statement": "The conclusion follows.",
                        "depends_on": [],
                        "check_type": "sufficiency",
                        "importance": "critical",
                    }
                ],
                "unresolved_obligations": [],
            }
        )


def test_runtime_does_not_start_repair_without_atomic_call_pair():
    client = _AtomicGateClient()
    config = replace(
        HarnessConfig(),
        max_model_calls=3,
        enable_router=False,
        enable_skills=False,
        enable_alternatives=False,
        enable_tools=True,
        enable_evidence=True,
        enable_proof_obligations=True,
        enable_verifier=True,
        enable_memory=False,
        enable_lemma_loop=False,
        enable_rag=False,
        enable_repair=True,
        enable_finalizer=False,
        enable_shadow=False,
        enable_long_horizon=False,
    )

    result = MathForgeHarness(client, config).solve(
        "Prove that x equals x.",
        {},
    )
    public_trace = project_judge_trace(
        result["trace"],
        final_response=result["final_response"],
    )
    gate = next(
        event
        for event in result["trace"]
        if event["event"] == "repair_actionability_gate"
    )
    planned = next(
        event
        for event in result["trace"]
        if event["event"] == "problem_obligations_planned"
    )
    effective = next(
        event
        for event in result["trace"]
        if event["event"] == "effective_config_snapshot"
    )["snapshot"]

    assert planned["timing"] == "before_solver"
    assert planned["obligations"]
    assert gate["actionable_claims"] == {
        "primary-1": ["host-c1"]
    }
    assert gate["atomic_budget_pair_available"] is False
    assert "RepairAgent" not in client.roles
    assert "Original candidate solution." in result["final_response"]
    assert effective["schema_version"] == "1.2"
    assert effective["features"]["verification_closure"][
        "soft_review_is_hard_complete"
    ] is False
    public_by_name = {
        event["event"]: event
        for event in public_trace
    }
    assert public_by_name["problem_obligations_planned"][
        "timing"
    ] == "before_solver"
    assert public_by_name["proof_completion_summary"][
        "evidence_tier"
    ] == "incomplete"
    assert public_by_name["candidate_arbitrated"][
        "selected_evidence_tier"
    ] == "incomplete"
    assert all(
        event["schema_version"] == JUDGE_TRACE_SCHEMA_VERSION
        for event in public_trace
    )
    assert "PRIVATE-" not in json.dumps(
        public_trace,
        ensure_ascii=False,
    )
