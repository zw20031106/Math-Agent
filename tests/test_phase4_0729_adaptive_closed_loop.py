from __future__ import annotations

import json

from mathforge.agents.verifier import VerifierSkepticAgent
from mathforge.harness.adaptive_fanout import AdaptiveFanoutPolicy
from mathforge.harness.budget import CallBudget
from mathforge.harness.provider import ModelCallGate, OfficialClientProvider
from mathforge.harness.schemas import (
    CandidateSolution,
    Claim,
    MethodStep,
    ProblemIR,
    ProofObligation,
    RoutePlan,
)
from mathforge.verification.proof_obligations import ProofObligationEngine


def _route(risk: str = "low") -> RoutePlan:
    return RoutePlan(
        primary_subject="general-math",
        auxiliary_subject=None,
        problem_type="calculation",
        answer_type="integer",
        risk_level=risk,
        candidate_count=3,
        method_families=[
            "direct-deduction",
            "constructive-computation",
            "contradiction",
        ],
    )


def _candidate(
    candidate_id: str = "primary-1",
    *,
    parse_tier: str = "strict",
) -> CandidateSolution:
    return CandidateSolution(
        candidate_id,
        "PrimarySolver",
        "direct-deduction",
        "2",
        "integer",
        claims=[
            Claim(
                "c1",
                "One plus one is two.",
                importance="critical",
            )
        ],
        public_solution_steps=["Add the two units."],
        solution_text="One plus one is two.",
        parse_tier=parse_tier,
        method_steps=[MethodStep("s1", "conclusion", ["c1"])],
    )


def _budget() -> CallBudget:
    budget = CallBudget(6)
    budget.consume(stage="primary")
    return budget


def test_low_risk_complete_primary_suppresses_no_benefit_alternatives():
    decision = AdaptiveFanoutPolicy().decide(
        _route("low"),
        _candidate(),
        _budget(),
        required_stage_reserve=1,
    )

    assert decision.requested_candidates == 3
    assert decision.admitted_candidates == 1
    assert "low_risk_primary_complete" in decision.reason_codes


def test_recovered_or_conflicting_primary_admits_at_most_two_alternatives():
    recovered = AdaptiveFanoutPolicy().decide(
        _route("medium"),
        _candidate(parse_tier="recovered"),
        _budget(),
        required_stage_reserve=1,
    )
    conflict = AdaptiveFanoutPolicy().decide(
        _route("low"),
        _candidate(),
        _budget(),
        required_stage_reserve=1,
        shadow_consistency="conflict",
    )

    assert recovered.admitted_candidates == 3
    assert conflict.admitted_candidates >= 2
    assert recovered.admitted_candidates - 1 <= 2


def test_public_operations_infer_theorem_and_interchange_obligations():
    candidate = _candidate()
    candidate.public_solution_steps = [
        "Write a double sum and interchange the order by absolute convergence.",
        "Apply the generating function identity.",
    ]
    candidate.claims[0].check_type = "interchange"
    candidate.method_steps = [
        MethodStep("s1", "theorem_application", ["c1"])
    ]
    obligations = ProofObligationEngine().generate(
        ProblemIR(
            raw_problem="Evaluate a convergent double sum.",
            normalized_problem="Evaluate a convergent double sum.",
            problem_type="calculation",
            answer_type="expression",
        ),
        candidate,
    )

    assert {"interchange", "theorem_preconditions"} <= {
        item.kind for item in obligations
    }


def test_joint_verifier_receives_conflict_matrix_in_one_call():
    calls: list[dict] = []

    class ReviewClient:
        def chat(self, **kwargs):
            calls.append(kwargs)
            return json.dumps({"findings": []})

    candidates = [
        _candidate("primary-1"),
        CandidateSolution(
            "alternative-1",
            "AlternativeSolver",
            "contradiction",
            "3",
            "integer",
            claims=[Claim("a1", "A conflicting answer.", importance="critical")],
            public_solution_steps=["Assume the contrary."],
            source="llm_alternative",
        ),
    ]
    obligations = {
        item.candidate_id: [
            ProofObligation(
                f"{item.candidate_id}:boundary",
                "boundary",
                "Check the boundary.",
                source_claim_ids=[item.claims[0].claim_id],
            )
        ]
        for item in candidates
    }
    result = VerifierSkepticAgent(
        OfficialClientProvider(ReviewClient(), ModelCallGate(1))
    ).review(
        ProblemIR(
            raw_problem="Compute.",
            normalized_problem="Compute.",
            problem_type="calculation",
            answer_type="integer",
        ),
        candidates,
        obligations,
        CallBudget(1),
        max_tokens=8192,
    )

    assert result.used_llm
    assert len(calls) == 1
    rendered = calls[0]["messages"][-1]["content"]
    assert "candidate_conflict_matrix" in rendered
    assert "primary-1" in rendered and "alternative-1" in rendered
