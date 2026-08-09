from __future__ import annotations

from dataclasses import replace
import json

from mathforge.agents.router_planner import RouterPlanner, derive_route_policy
from mathforge.agents.solver import PrimarySolver, SolverExecutor, SolverRequest
from mathforge.config import HarnessConfig
from mathforge.evaluation.scoring import score_response
from mathforge.harness.budget import CallBudget
from mathforge.harness.provider import ModelCallGate, OfficialClientProvider
from mathforge.output.gradeability import (
    enforce_scorer_round_trip,
    is_gradeable_response,
)
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.parsing.solution_parser import SolutionParser
from mathforge.runtime import MathForgeHarness


def _availability_config() -> HarnessConfig:
    return replace(
        HarnessConfig(),
        profile="phase2-availability",
        max_model_calls=8,
        max_logical_model_calls_per_problem=8,
        soft_call_checkpoints=(4, 6),
        speculative_exploration_cutoff=7,
        closure_reserve_calls=1,
        enable_router=False,
        enable_skills=False,
        enable_alternatives=True,
        enable_tools=False,
        enable_evidence=False,
        enable_proof_obligations=False,
        enable_peer_cross_review=False,
        enable_verification_closure=False,
        enable_verifier=False,
        enable_memory=False,
        enable_lemma_loop=False,
        enable_rag=False,
        enable_repair=False,
        enable_finalizer=False,
        enable_final_audit=False,
        enable_shadow=False,
        enable_long_horizon=False,
    )


class EmergencyOnlyClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def chat(self, *, messages, temperature, max_tokens):
        del temperature, max_tokens
        system = messages[0]["content"]
        self.calls.append(system.splitlines()[0])
        if "final gradeability fallback" in system:
            return json.dumps({"answer": "4", "check": "$2+2=4$."})
        return "not a structured candidate"


def test_router_policy_keeps_primary_and_independent_alternative_backbone() -> None:
    assert derive_route_policy("low", "computation").candidate_count == 2
    assert derive_route_policy("medium", "computation").candidate_count == 2
    assert derive_route_policy("high", "proof").candidate_count == 3


def test_answer_salvage_is_explicitly_degraded_not_hard_verified() -> None:
    response = (
        '{"protocol_version":"1.0","task_result_type":"CandidateArtifact",'
        '"action":"publish_candidate","result_payload":{"answer":"4",'
        '"check":"$2+2=4$."'
    )
    candidate = SolutionParser().recover_answer_candidate(
        response,
        candidate_id="salvaged",
        role="PrimarySolver",
        answer_type="integer",
        planned_method_family="direct-deduction",
    )

    assert candidate is not None
    assert candidate.final_answer == "4"
    assert candidate.parse_tier == "answer_recovered"
    assert candidate.claims == []
    assert "answer_only_salvage" in candidate.contract_deviations


def test_damaged_agent_turn_recovers_complete_inner_answer() -> None:
    class DamagedTurnClient:
        def chat(self, **_kwargs):
            return (
                '{"protocol_version":"1.0","task_result_type":'
                '"CandidateArtifact","action":"publish_candidate",'
                '"result_payload":{"answer":"4","check":"2+2=4"'
            )

    problem = ProblemParser().parse("Compute 2+2.")
    route = RouterPlanner().plan(problem)
    candidate = SolverExecutor(
        OfficialClientProvider(DamagedTurnClient(), ModelCallGate(1)),
        SolutionParser(),
    ).execute_autonomous_candidate(
        PrimarySolver(),
        SolverRequest(
            "damaged-turn",
            problem,
            route,
            "",
            route.method_families[0],
        ),
        CallBudget(2),
        temperature=0.0,
        max_tokens=2048,
    ).candidate

    assert candidate is not None
    assert candidate.final_answer == "4"
    assert candidate.parse_tier == "answer_recovered"


def test_emergency_direct_solver_returns_gradeable_answer_after_branch_failures() -> None:
    client = EmergencyOnlyClient()
    result = MathForgeHarness(client, _availability_config()).solve(
        "Compute 2+2.",
        {"idx": "phase2-emergency"},
    )

    assert result["run_metrics"]["outcome"] == "primary"
    assert is_gradeable_response(result["final_response"], "integer")
    emergency = next(
        event
        for event in result["trace"]
        if event["event"] == "candidate_generated" and event.get("emergency")
    )
    assert emergency["parse_tier"] == "recovered"
    assert any(
        event["event"] == "candidate_generation_started"
        and event.get("replacement")
        for event in result["trace"]
    )


def test_formatter_scorer_round_trip_repairs_competing_decimal_answer() -> None:
    response, result = enforce_scorer_round_trip(
        "A numerical approximation is useful.\n\nFinal answer: 4.1667",
        exact_answer="25/6",
        answer_type="fraction",
        response_mode="worked_solution",
    )

    assert result.status == "pass"
    assert result.reformatted is True
    assert result.extracted_canonical == "25/6"
    assert is_gradeable_response(response, "fraction")


def test_scorer_accepts_formatter_text_and_choice_wrappers() -> None:
    assert score_response(
        "QED",
        r"Final answer: $\text{QED}$",
        answer_type="text",
        scorer="exact",
    ).correct
    assert score_response(
        "B",
        r"Final answer: $\mathrm{B}$",
        answer_type="choice",
        scorer="exact",
    ).correct


def test_twenty_case_gradeability_canary_has_no_format_loss() -> None:
    outputs = [
        MathForgeHarness(EmergencyOnlyClient(), _availability_config()).solve(
            "Compute 2+2.",
            {"idx": f"phase2-gradeability-{index}"},
        )["final_response"]
        for index in range(20)
    ]
    assert sum(is_gradeable_response(item, "integer") for item in outputs) == 20
