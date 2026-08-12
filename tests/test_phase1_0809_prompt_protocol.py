from __future__ import annotations

from dataclasses import replace
import json

import pytest

from mathforge.agent_runtime.protocol import AgentTurnPayloadParser
from mathforge.agent_runtime.router_protocol import (
    ROUTER_INTENT_FIELDS,
    parse_router_intent,
)
from mathforge.agents.prompt_compiler import PromptCompiler
from mathforge.agents.registry import PromptContractLoader
from mathforge.agents.router_planner import RouterPlanner, RouterRuleEngine
from mathforge.agents.solver import PrimarySolver, SolverRequest
from mathforge.harness.budget import CallBudget
from mathforge.harness.model_candidate_contract import (
    MODEL_CANDIDATE_PROFILE_FIELDS,
)
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.parsing.solution_parser import (
    SolutionParser,
    candidate_response_validation,
)
from mathforge.parsing.structured_output import (
    StructuredOutputRecoveryLayer,
    json_latex_lexical_issues,
)
from mathforge.runtime import MathForgeHarness
from tests.test_phase2_concurrency_lifecycle import _minimal_config


def _router_payload(index: int = 0) -> dict:
    return {
        "primary_domain": "general-math",
        "secondary_domain": None,
        "risk": "high",
        "patterns": [f"canary-{index}"],
        "preferred_methods": ["direct-deduction"],
        "alternative_methods": ["constructive-computation"],
        "needs_long_horizon": True,
    }


def test_compiled_router_schema_matches_router_parser() -> None:
    compilation = PromptCompiler().compile_role(
        "router_planner",
        user_content="Problem: compute 2+2",
    )
    assert set(compilation.output_schema_fields) == ROUTER_INTENT_FIELDS
    assert "task_proposals" not in compilation.messages[0]["content"]
    assert "subgoals" in compilation.messages[0]["content"]
    assert "Host owns subgoals" in compilation.messages[0]["content"]

    intent, tier, _, degradation = parse_router_intent(
        json.dumps(_router_payload()),
        allowed_domains={"general-math"},
    )
    assert intent.primary_domain == "general-math"
    assert tier == "strict_json"
    assert degradation == "none"


def test_router_production_protocol_canary_accepts_all_twelve_cases() -> None:
    problem = ProblemParser().parse("Prove a difficult mathematical statement.")
    outcomes = [
        RouterPlanner().plan_authoritative(
            problem,
            llm_chat=lambda index=index, **_: json.dumps(_router_payload(index)),
            consume_call=lambda: None,
        )
        for index in range(12)
    ]
    assert sum(outcome.source == "llm_router" for outcome in outcomes) == 12
    assert all(outcome.authoritative_plan.subgoals for outcome in outcomes)
    assert all(outcome.authoritative_plan.task_proposals for outcome in outcomes)
    assert all(
        outcome.protocol_parse_tier == "strict_json" for outcome in outcomes
    )


def test_twelve_case_harness_canary_uses_router_and_candidate_protocols() -> None:
    class CanaryClient:
        def chat(self, *, messages, temperature, max_tokens):
            system = messages[0]["content"]
            if system.startswith("You are RouterPlanner"):
                return json.dumps(_router_payload())
            return json.dumps(
                {
                    "answer": "4",
                    "method": "direct-deduction",
                    "steps": ["$2+2=4$."],
                    "uncertainties": [],
                }
            )

    results = [
        MathForgeHarness(
            CanaryClient(),
            _minimal_config(max_model_calls=2, enable_router=True),
        ).solve("Compute 2+2.", {"idx": f"phase1-canary-{index}"})
        for index in range(12)
    ]
    assert all(result["run_metrics"]["outcome"] == "primary" for result in results)
    for result in results:
        route = next(
            event for event in result["trace"] if event["event"] == "route_planned"
        )
        assert route["router_source"] == "llm_router"
        assert route["protocol_parse_tier"] == "strict_json"


def test_contract_runtime_source_of_truth_and_prompt_snapshot() -> None:
    loader = PromptContractLoader()
    contract = loader.load("primary_solver")
    problem = ProblemParser().parse("Compute 2+2.")
    route = RouterRuleEngine().plan(problem)
    compilation = PrimarySolver(loader).compile_prompt(
        SolverRequest(
            "source-of-truth",
            problem,
            route,
            "",
            route.method_families[0],
        )
    )
    system = compilation.messages[0]["content"]
    assert contract.body.strip() in system
    assert compilation.contract_sha256 == contract.source_sha256
    assert len(compilation.prompt_sha256) == 64
    repeated = PrimarySolver(loader).compile_prompt(
        SolverRequest(
            "source-of-truth",
            problem,
            route,
            "",
            route.method_families[0],
        )
    )
    assert repeated.prompt_sha256 == compilation.prompt_sha256


@pytest.mark.parametrize(
    ("problem_text", "profile", "cap"),
    [
        ("Compute 17+28.", "simple", 2048),
        (
            "Evaluate the integral under the stated assumptions and show every "
            "required derivation step without treating this as a proof.",
            "standard",
            32768,
        ),
        ("Prove that x^2 is nonnegative for every real x.", "proof", 40960),
    ],
)
def test_candidate_profile_schema_and_budget(
    problem_text: str,
    profile: str,
    cap: int,
) -> None:
    problem = ProblemParser().parse(problem_text)
    route = RouterRuleEngine().plan(problem)
    if profile == "standard":
        route = replace(route, risk_level="high")
    compilation = PrimarySolver().compile_prompt(
        SolverRequest("profile", problem, route, "", route.method_families[0])
    )
    assert PromptCompiler.candidate_output_profile(problem, route) == profile
    assert set(compilation.output_schema_fields) == MODEL_CANDIDATE_PROFILE_FIELDS[
        profile
    ]
    assert compilation.max_output_tokens == cap


def test_simple_candidate_is_host_normalized_but_not_hard_verified() -> None:
    candidate = SolutionParser().parse(
        json.dumps({"answer": "45", "check": "$17+28=45$."}),
        candidate_id="simple",
        role="PrimarySolver",
        answer_type="integer",
        planned_method_family="direct-deduction",
    )
    assert candidate.final_answer == "45"
    assert candidate.parse_tier == "recovered"
    assert candidate_response_validation(candidate) == (
        "recovered_candidate_json",
        False,
    )
    assert all(claim.status == "unverified" for claim in candidate.claims)


def test_agent_turn_truncated_payload_salvage() -> None:
    response = (
        '{"protocol_version":"1.0","task_result_type":"CandidateArtifact",'
        '"action":"publish_candidate","public_state_delta":{},'
        '"result_payload":{"answer":"4","check":"$2+2=4$."}'
    )
    parsed = AgentTurnPayloadParser().parse(
        response,
        allowed_actions=("publish_candidate",),
        truncated=True,
        truncation_reason="finish_reason_length",
    )
    assert parsed.payload.result_payload["answer"] == "4"
    assert parsed.partial is True
    assert parsed.parse_tier == "semantic_salvage"
    assert parsed.assurance_degradation == "high"


def test_agent_turn_outer_schema_damage_salvages_public_payload_only() -> None:
    payload = {
        "protocol_version": "1.0",
        "task_result_type": "CandidateArtifact",
        "action": "publish_candidate",
        "public_state_delta": {},
        "result_payload": {"answer": "4", "check": "$2+2=4$."},
        "outbound_intents": [],
        "progress_summary": "candidate ready",
        "stop_reason": "",
        "unexpected_wrapper_field": "ignored with degradation",
    }
    parsed = AgentTurnPayloadParser().parse(
        json.dumps(payload),
        allowed_actions=("publish_candidate",),
    )
    assert parsed.payload.result_payload["answer"] == "4"
    assert parsed.parse_tier == "semantic_salvage"
    assert parsed.assurance_degradation == "high"

    payload["agent_id"] = "model-must-not-own-this"
    with pytest.raises(ValueError, match="Host-owned"):
        AgentTurnPayloadParser().parse(json.dumps(payload))


def test_json_latex_control_escape_roundtrip() -> None:
    invalid = r'{"answer":"\frac{1}{2}","check":"\theta>0"}'
    assert json_latex_lexical_issues(invalid)
    recovered = StructuredOutputRecoveryLayer().parse_object(invalid)
    assert recovered.value == {"answer": r"\frac{1}{2}", "check": r"\theta>0"}
    assert recovered.parse_tier == "trailing_repair"
    assert recovered.assurance_degradation == "medium"


def test_per_stage_protocol_telemetry_records_recovery() -> None:
    budget = CallBudget(1)
    index = budget.record_model_call_started(
        "primary",
        {
            "prompt_tokens": 16,
            "max_output_tokens": 1024,
            "counting_mode": "fallback_estimate",
            "turn_kind": "solver_candidate_standard",
        },
    )
    budget.record_model_protocol_telemetry(
        index,
        "semantic_salvage",
        "complete_public_fields_from_truncated_turn",
        "high",
        candidate_parse_tier="recovered",
    )
    record = budget.model_call_records[index]
    assert record["protocol_parse_tier"] == "semantic_salvage"
    assert record["protocol_assurance_degradation"] == "high"
    assert record["candidate_parse_tier"] == "recovered"
