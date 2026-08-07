from __future__ import annotations

import json
from pathlib import Path

from mathforge.agents.router_planner import RouterRuleEngine
from mathforge.agents.solver import PrimarySolver, SolverRequest
from mathforge.config import HarnessConfig
from mathforge.harness.adaptive_fanout import AdaptiveFanoutPolicy
from mathforge.harness.allocation import CallAllocationPlan
from mathforge.harness.budget import CallBudget
from mathforge.harness.schemas import CandidateSolution, Claim, ProblemIR
from mathforge.output.judge_trace import project_judge_trace
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.runtime import MathForgeHarness
from mathforge.verification.admission import CandidateAdmissionGate
from tests.fake_client import FakeClient


ROOT = Path(__file__).resolve().parents[1]
HIGH_DIFFICULTY = (
    ROOT / "tests" / "fixtures" / "phase0_general_high_difficulty.jsonl"
)
ADVERSARIAL = (
    ROOT / "tests" / "fixtures" / "phase0_contract_adversarial.jsonl"
)


def _rows(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _candidate(
    *,
    answer_type: str = "expression",
    final_answer: str = "2",
    claims: list[Claim] | None = None,
) -> CandidateSolution:
    return CandidateSolution(
        candidate_id="primary-1",
        role="PrimarySolver",
        method="direct-deduction",
        final_answer=final_answer,
        answer_type=answer_type,
        public_solution_steps=["Compute directly."],
        claims=claims or [
            Claim(
                "c1",
                "The stated final answer follows.",
                importance="critical",
            )
        ],
        parse_status="strict_json",
        parse_tier="strict",
    )


def _config(**overrides) -> HarnessConfig:
    values = {
        "profile": "phase3-test",
        "status": "test",
        "max_model_calls": 1,
        "enable_router": False,
        "enable_skills": False,
        "enable_alternatives": False,
        "enable_tools": False,
        "enable_evidence": False,
        "enable_proof_obligations": False,
        "enable_verifier": False,
        "enable_memory": False,
        "enable_lemma_loop": False,
        "enable_rag": False,
        "enable_repair": False,
        "enable_finalizer": False,
    }
    values.update(overrides)
    return HarnessConfig(**values)


def test_reliable_option_enumeration_rejects_bare_line_leading_letters():
    parser = ProblemParser()
    bare = parser.parse(
        "A finite graph is connected.\n"
        "B vertices may have odd degree.\n"
        "Prove the stated theorem."
    )
    punctuated = parser.parse(
        "Select the correct value.\nA. 1\nB) 2\n(C) 3"
    )

    assert bare.problem_type == "proof"
    assert bare.options == []
    assert punctuated.problem_type == "multiple_choice"
    assert punctuated.answer_type == "choice"
    assert punctuated.options == ["1", "2", "3"]


def test_problem_ir_v2_round_trip_has_structural_fields():
    problem = ProblemParser().parse(
        "Let f:[0,1]->R be twice continuously differentiable, "
        "f(0)=f(1)=0, and |f''(x)|<=1 for every x. "
        "Determine the sharp upper bound."
    )
    restored = ProblemIR.from_dict(problem.to_dict())

    assert restored.schema_version == ProblemIR.SCHEMA_VERSION
    assert restored.definitions
    assert restored.quantifiers
    assert len(restored.constraints) >= 3
    assert restored.target_kind == "compute_value"
    assert "long_condition_chain" in restored.difficulty_features
    assert "establish_domain_and_constraints" in restored.subproblem_hints


def test_phase0_contract_adversarial_parser_gate_is_fully_satisfied():
    parsed = {
        row["idx"]: ProblemParser().parse(row["problem"])
        for row in _rows(ADVERSARIAL)
    }

    assert all(item.problem_type != "multiple_choice" for item in parsed.values())
    assert parsed["ca-001"].problem_type == "proof"
    assert parsed["ca-001"].options == []
    assert "long_condition_chain" in parsed["ca-002"].difficulty_features
    assert parsed["ca-003"].target_kind == "multiple_targets"
    assert "multiple_targets" in parsed["ca-003"].difficulty_features
    assert "nested_quantifiers" in parsed["ca-004"].difficulty_features
    assert "candidate_conflict" in parsed["ca-005"].difficulty_features
    assert parsed["ca-006"].normalized_problem


def test_low_confidence_answer_type_is_soft_but_empty_answer_remains_hard():
    problem = ProblemParser().parse(
        "Find all real x satisfying x^2=1."
    )
    assert problem.answer_type == "expression"
    assert problem.answer_type_confidence < 0.85

    recovered = CandidateAdmissionGate().evaluate(
        _candidate(answer_type="set", final_answer="{-1,1}"),
        problem,
    )
    empty = CandidateAdmissionGate().evaluate(
        _candidate(answer_type="set", final_answer=""),
        problem,
    )

    assert recovered.accepted
    assert "low_confidence_answer_type_soft_gate" in recovered.warning_codes
    assert "normalization_recovery:set" in recovered.warning_codes
    assert not empty.accepted
    assert "empty_answer" in empty.rejection_codes


def test_general_high_difficulty_route_recall_and_simple_false_promotion_gate():
    parser = ProblemParser()
    router = RouterRuleEngine()
    difficult = [
        router.plan(parser.parse(row["problem"])).risk_level
        for row in _rows(HIGH_DIFFICULTY)
    ]
    simple = [
        "Compute 2+2.",
        "Solve x+1=3.",
        "Find the derivative of x^2.",
        "Find the area of a unit square.",
        "Evaluate 3!.",
    ]
    simple_risks = [
        router.plan(parser.parse(problem)).risk_level
        for problem in simple
    ]

    assert difficult.count("high") / len(difficult) >= 0.90
    assert "high" not in simple_risks


def test_primary_posterior_signal_admits_the_reserved_alternative():
    problem = ProblemParser().parse("Compute 2+2.")
    route = RouterRuleEngine().plan(problem)
    route.candidate_count = 2
    route.risk_level = "low"
    primary_without_critical_claim = _candidate(
        claims=[Claim("c1", "A supporting statement.")],
    )
    budget = CallBudget(3)
    budget.set_allocation_plan(
        CallAllocationPlan.build(
            max_calls=3,
            router_calls=0,
            candidate_count=2,
            verifier_required=False,
            repair_requested=False,
            lemma_requested=False,
            finalizer_requested=False,
        )
    )
    budget.consume(stage="primary")

    decision = AdaptiveFanoutPolicy().decide(
        route,
        primary_without_critical_claim,
        budget,
        required_stage_reserve=0,
    )

    assert decision.admitted_candidates == 2
    assert "primary_posterior_escalation" in decision.reason_codes
    assert "posterior:missing_critical_claim" in decision.reason_codes


def test_solver_prompt_receives_bounded_public_problem_structure():
    problem = ProblemParser().parse(
        "Find all real a for which x^2-2ax+a+2=0 has "
        "two distinct positive real roots."
    )
    route = RouterRuleEngine().plan(problem)
    messages = PrimarySolver().build_messages(
        SolverRequest(
            "primary-1",
            problem,
            route,
            "",
            route.method_families[0],
        )
    )
    user = messages[-1]["content"]

    assert "Host-parsed public problem structure:" in user
    assert "Target kind:" in user
    assert "Structural difficulty: parameter_regime" in user
    assert "Suggested decomposition:" in user


def test_effective_config_is_public_and_empty_frozen_store_is_disabled():
    harness = MathForgeHarness(
        FakeClient(),
        _config(enable_frozen_lemma_store=True),
    )
    result = harness.solve("Compute 1+1.", {})
    public_trace = project_judge_trace(
        result["trace"],
        final_response=result["final_response"],
    )
    effective = next(
        event
        for event in result["trace"]
        if event["event"] == "effective_config_snapshot"
    )["snapshot"]
    budget = next(
        event
        for event in public_trace
        if event["event"] == "budget_summary"
    )
    model_activity = next(
        event
        for event in public_trace
        if event["event"] == "model_activity"
    )

    assert effective["provider"]["interface"] == "injected_client.chat"
    assert effective["provider"]["max_physical_concurrency"] == 16
    assert effective["prompt"]["stage_output_cap_tokens"]["primary"] == 8192
    assert effective["deadline"]["hard_deadline_seconds"] == 870.0
    assert effective["features"]["frozen_lemma_store"] == {
        "requested": True,
        "effective": False,
        "record_count": 0,
        "disabled_reason": "empty_store",
    }
    assert harness._frozen_lemma_store is None
    assert budget["model_calls"] == model_activity["call_count"]
    call = model_activity["calls"][0]
    assert {
        "prompt_tokens",
        "configured_output_tokens",
        "stage_output_cap_tokens",
        "max_output_tokens",
        "context_window_tokens",
        "safety_margin_tokens",
        "stage_p95_seconds",
        "effective_queue_budget_seconds",
        "agent_wait_seconds",
        "scheduler_wait_seconds",
        "rate_wait_seconds",
        "call_id",
        "logical_call_index",
        "logical_call_consumed",
        "dispatched",
        "turn_kind",
        "requested_max_output_tokens",
        "effective_max_output_tokens",
        "stage_timeout_seconds",
        "effective_stage_timeout_seconds",
        "tail_state",
        "stop_reason",
    } <= set(call)
