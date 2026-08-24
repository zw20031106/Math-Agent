from __future__ import annotations

import json

import pytest

from mathforge.agent_runtime.protocol import AGENT_TURN_FIELDS
from mathforge.agents.prompt_compiler import PromptCompiler
from mathforge.agents.router_planner import RouterRuleEngine
from mathforge.agents.solver import PrimarySolver, SolverRequest
from mathforge.harness.model_candidate_contract import (
    MODEL_CANDIDATE_PROFILE_FIELDS,
    candidate_profile_example,
    candidate_profile_for_response_mode,
    validate_candidate_profile,
)
from mathforge.harness.reasoning_state import (
    ProgressDeltaParser,
    ReasoningStateValidationError,
)
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.parsing.solution_parser import SolutionParser


@pytest.mark.parametrize(
    ("problem", "profile"),
    [
        ("Compute 2+2.", "answer_only"),
        ("Compute 2+2 and show your work.", "worked_solution"),
        ("Prove that 2+2=4.", "proof_full"),
    ],
)
def test_candidate_profile_is_owned_by_response_mode(problem: str, profile: str) -> None:
    parsed = ProblemParser().parse(problem)
    route = RouterRuleEngine().plan(parsed)

    assert candidate_profile_for_response_mode(parsed.response_mode) == profile
    assert PromptCompiler.candidate_output_profile(parsed, route) == profile


@pytest.mark.parametrize("profile", ["answer_only", "worked_solution", "proof_full"])
def test_schema_generated_candidate_example_validates_with_same_definition(
    profile: str,
) -> None:
    example = candidate_profile_example(profile)

    validate_candidate_profile(example, profile)
    assert set(example) == MODEL_CANDIDATE_PROFILE_FIELDS[profile]


def test_autonomous_candidate_turn_compiles_one_outer_schema_without_boxed_rules() -> None:
    problem = ProblemParser().parse("Compute 2+2.")
    route = RouterRuleEngine().plan(problem)
    compilation = PrimarySolver().compile_prompt(
        SolverRequest("phase2", problem, route, "", route.method_families[0]),
        autonomous=True,
    )
    system = compilation.messages[0]["content"]

    assert compilation.output_schema_name == "agent_turn:candidate:answer_only"
    assert set(compilation.output_schema_fields) == AGENT_TURN_FIELDS
    assert system.count("Exact JSON schema example:") == 1
    assert "ModelCandidatePayload" not in system
    assert "optional exposition" not in system
    assert "\\boxed" not in system
    assert "final answer first" not in system.lower()


def test_response_profile_parser_preserves_claim_kind_and_host_assigns_ids() -> None:
    payload = {
        "final_answer": "4",
        "method": "direct-deduction",
        "steps": [
            {
                "statement": "$2+2=4$.",
                "claim_kind": "equality",
                "depends_on": [],
            },
            {
                "statement": "Therefore the requested value is $4$.",
                "claim_kind": "answer_shape",
                "depends_on": [0],
            },
        ],
        "uncertainties": [],
    }

    candidate = SolutionParser().parse(
        json.dumps(payload),
        candidate_id="profile",
        role="PrimarySolver",
        answer_type="integer",
        planned_method_family="direct-deduction",
        response_mode="worked_solution",
    )

    assert candidate.parse_tier == "strict"
    assert candidate.contract_deviations == []
    assert [claim.claim_id for claim in candidate.claims] == [
        "host-c1",
        "host-c2",
    ]
    assert candidate.claims[1].depends_on == ["host-c1"]
    assert [claim.claim_kind for claim in candidate.claims] == [
        "equality",
        "answer_shape",
    ]
    assert all(step.step_id.startswith("host-s") for step in candidate.method_steps)


def test_progress_turn_accepts_semantics_and_host_assigns_lifecycle_fields() -> None:
    payload = {
        "public_summary": "Established the arithmetic relation.",
        "strategy": "direct-deduction",
        "subgoals": [
            {
                "statement": "Compute the sum.",
                "depends_on": [],
                "exit_condition": "The exact value is obtained.",
            }
        ],
        "claims": [
            {
                "statement": "$2+2=4$.",
                "claim_kind": "equality",
                "depends_on": [],
                "subgoal_refs": [0],
                "importance": "critical",
            }
        ],
        "open_obligations": [],
        "closed_obligation_ids": [],
        "contradictions": [],
        "next_step": "Synthesize the candidate.",
        "stop_reason": "ready_for_candidate",
    }

    delta = ProgressDeltaParser().parse(
        json.dumps(payload),
        round_index=1,
        mode="explore",
        branch_id="branch-test",
    )

    assert delta.subgoals[0].subgoal_id == "host-r1-g1"
    assert delta.subgoals[0].status == "open"
    assert delta.claims[0].claim_id == "host-r1-c1"
    assert delta.claims[0].version == 1
    assert delta.claims[0].status == "proposed"
    assert delta.claims[0].claim_kind == "equality"


def test_progress_turn_rejects_model_owned_lifecycle_fields() -> None:
    payload = {
        "public_summary": "Progress.",
        "strategy": "direct-deduction",
        "subgoals": [],
        "claims": [
            {
                "claim_id": "model-c1",
                "statement": "$2+2=4$.",
                "claim_kind": "equality",
                "depends_on": [],
                "subgoal_refs": [],
                "importance": "critical",
                "version": 99,
                "status": "verified",
            }
        ],
        "open_obligations": [],
        "closed_obligation_ids": [],
        "contradictions": [],
        "next_step": "Finish.",
        "stop_reason": "",
    }

    with pytest.raises(ReasoningStateValidationError, match="Host-owned"):
        ProgressDeltaParser().parse(
            json.dumps(payload),
            round_index=1,
            mode="explore",
        )


def test_answer_salvage_does_not_invent_a_derivation_step() -> None:
    candidate = SolutionParser().recover_answer_candidate(
        '{"final_answer":"4"',
        candidate_id="truncated",
        role="PrimarySolver",
        answer_type="integer",
    )

    assert candidate is not None
    assert candidate.final_answer == "4"
    assert candidate.solution_text == ""
    assert candidate.public_solution_steps == []
