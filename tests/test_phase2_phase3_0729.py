from __future__ import annotations

import json

import pytest

from mathforge.agents.repair import RepairAgent
from mathforge.agents.router_planner import RouterRuleEngine
from mathforge.agents.solver import PrimarySolver, SolverExecutor, SolverRequest
from mathforge.harness.allocation import CallAllocationPlan, FanoutDecision
from mathforge.harness.budget import CallBudget
from mathforge.harness.errors import ModelTransportError
from mathforge.harness.provider import ModelCallGate, OfficialClientProvider
from mathforge.harness.schemas import (
    CandidatePatch,
    CandidateSolution,
    Claim,
)
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.parsing.solution_parser import (
    SolutionParser,
    candidate_response_validation,
)
from mathforge.verification.admission import CandidateAdmissionGate
from mathforge.verification.cross_review import (
    CandidateConflictMatrix,
    CandidateReviewSummary,
)


def _payload(method: str = "direct-deduction") -> dict:
    return {
        "method": method,
        "final_answer": "2",
        "public_solution_steps": ["Add the two unit quantities."],
        "claims": [
            {
                "claim_id": "c1",
                "statement": "The sum is 2.",
                "depends_on": [],
                "check_type": "reasoning",
                "importance": "critical",
            }
        ],
        "solution_text": "Adding one and one gives two.",
        "assumptions": [],
        "theorems": [],
        "unresolved_obligations": [],
    }


def _solver_request() -> SolverRequest:
    problem = ProblemParser().parse("Compute 1+1.")
    route = RouterRuleEngine().plan(problem)
    return SolverRequest(
        candidate_id="primary-1",
        problem=problem,
        route=route,
        skill_context="",
        method_family=route.method_families[0],
    )


def test_budget_snapshot_and_fanout_decision_are_serializable_foundations():
    budget = CallBudget(6)
    plan = CallAllocationPlan.build(
        max_calls=6,
        router_calls=0,
        candidate_count=2,
        verifier_required=True,
        repair_requested=False,
        lemma_requested=False,
        finalizer_requested=False,
    )
    budget.set_allocation_plan(plan)
    budget.consume(stage="primary")
    snapshot = budget.snapshot()
    decision = FanoutDecision(2, 2, ("budget_available",), snapshot)

    assert snapshot.used_calls == 1
    assert snapshot.remaining_calls == 5
    assert snapshot.stage_remaining["primary"] == plan.primary - 1
    assert decision.to_dict()["budget"]["remaining_calls"] == 5


def test_primary_does_not_retry_a_nonrecoverable_auth_failure():
    class AuthFailureClient:
        def __init__(self) -> None:
            self.calls = 0

        def chat(self, **_kwargs):
            self.calls += 1
            raise RuntimeError("401 unauthorized")

    client = AuthFailureClient()
    executor = SolverExecutor(
        OfficialClientProvider(client, ModelCallGate(1)),
        SolutionParser(),
    )
    with pytest.raises(ModelTransportError) as captured:
        executor.execute(
            PrimarySolver(),
            _solver_request(),
            CallBudget(2),
            temperature=0.0,
            max_tokens=8192,
        )

    assert captured.value.code == "auth_or_permission_failure"
    assert client.calls == 1


def test_host_owns_identity_source_tier_and_constructs_method_steps():
    payload = _payload()
    payload.update(
        {
            "candidate_id": "model-controlled",
            "role": "AlternativeSolver",
            "source": "deterministic_shadow",
            "parse_tier": "rejected",
        }
    )
    candidate = SolutionParser().parse(
        json.dumps(payload),
        candidate_id="primary-1",
        role="PrimarySolver",
        answer_type="integer",
    )

    assert candidate.candidate_id == "primary-1"
    assert candidate.role == "PrimarySolver"
    assert candidate.source == "llm_primary"
    assert candidate.parse_tier == "recovered"
    assert candidate.method_steps[0].step_id == "host-s1"
    assert candidate_response_validation(candidate) == (
        "recovered_candidate_json",
        False,
    )


def test_parser_recovers_the_complete_candidate_at_the_end_of_a_long_response():
    response = (
        '{"partial":{"nested":true}\n'
        + ("public explanation " * 500)
        + "\n"
        + json.dumps(_payload())
    )
    candidate = SolutionParser().parse(
        response,
        candidate_id="tail",
        role="PrimarySolver",
        answer_type="integer",
    )

    assert candidate.final_answer == "2"
    assert candidate.parse_tier == "recovered"
    assert candidate_response_validation(candidate)[1] is False


def test_method_wording_difference_is_recorded_without_a_second_model_call():
    class RenamedMethodClient:
        def __init__(self) -> None:
            self.calls = 0

        def chat(self, **_kwargs):
            self.calls += 1
            return json.dumps(_payload("equivalent direct calculation"))

    client = RenamedMethodClient()
    candidate = SolverExecutor(
        OfficialClientProvider(client, ModelCallGate(1)),
        SolutionParser(),
    ).execute(
        PrimarySolver(),
        _solver_request(),
        CallBudget(2),
        temperature=0.0,
        max_tokens=8192,
    )

    assert client.calls == 1
    assert "method:planned_method_family" in candidate.contract_deviations


def test_answer_recovery_requires_the_deterministic_answer_gate():
    problem = ProblemParser().parse("Compute 1+1.")
    candidate = SolutionParser().parse(
        "A concise derivation.\nFinal answer: 2",
        candidate_id="answer-only",
        role="PrimarySolver",
        answer_type=problem.answer_type,
    )
    gate = CandidateAdmissionGate()

    assert candidate.parse_tier == "answer_recovered"
    assert gate.evaluate(
        candidate,
        problem,
        answer_shape_status="pass",
    ).accepted
    rejected = gate.evaluate(
        candidate,
        problem,
        answer_shape_status="fail",
    )
    assert not rejected.accepted
    assert "answer_recovery_evidence_gate_failed" in rejected.rejection_codes


def test_repair_agent_returns_a_claim_local_patch_schema():
    candidate = CandidateSolution(
        "primary-1",
        "PrimarySolver",
        "direct-deduction",
        "2",
        "integer",
        claims=[
            Claim("base", "One is a unit."),
            Claim("failed", "The sum is 3.", ["base"]),
        ],
    )

    class PatchClient:
        def chat(self, **_kwargs):
            return json.dumps(
                {
                    "replacement_claims": [
                        {
                            "claim_id": "failed",
                            "statement": "One plus one is 2.",
                            "depends_on": ["base"],
                            "check_type": "reasoning",
                            "importance": "critical",
                        }
                    ],
                    "final_answer": "2",
                    "public_solution_steps": ["Correct the local addition."],
                    "unresolved_obligations": [],
                }
            )

    patch = RepairAgent(
        OfficialClientProvider(PatchClient(), ModelCallGate(1)),
        SolutionParser(),
    ).repair(
        ProblemParser().parse("Compute 1+1."),
        candidate,
        ["failed"],
        [],
        CallBudget(1),
        max_tokens=8192,
    )

    assert isinstance(patch, CandidatePatch)
    assert [claim.claim_id for claim in patch.replacement_claims] == ["failed"]
    assert "method" not in patch.to_dict()
    assert "solution_text" not in patch.to_dict()


def test_cross_review_contract_contains_public_summary_only():
    left = CandidateSolution(
        "left",
        "PrimarySolver",
        "direct",
        "2",
        "integer",
        claims=[Claim("c1", "One plus one is two.", importance="critical")],
        public_solution_steps=["Add the units."],
        solution_text="This field must not enter cross review.",
    )
    right = CandidateSolution(
        "right",
        "AlternativeSolver",
        "counting",
        "3",
        "integer",
        claims=[Claim("c2", "A conflicting count.", importance="critical")],
        public_solution_steps=["Count the units."],
        source="llm_alternative",
    )
    summaries = [
        CandidateReviewSummary.from_candidate(left),
        CandidateReviewSummary.from_candidate(right),
    ]
    serialized = json.dumps(
        {
            "summaries": [item.to_dict() for item in summaries],
            "matrix": CandidateConflictMatrix.build(summaries).to_dict(),
        }
    )

    assert "solution_text" not in serialized
    assert "must not enter cross review" not in serialized
    assert CandidateConflictMatrix.build(summaries).conflicts[0].answer_conflict
