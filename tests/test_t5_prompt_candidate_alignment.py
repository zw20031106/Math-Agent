from __future__ import annotations

import json

import pytest

from mathforge.agents.router_planner import RouterRuleEngine
from mathforge.agents.solver import PrimarySolver, SolverRequest
from mathforge.harness.model_candidate_contract import (
    ANSWER_ONLY_CANDIDATE_FIELDS,
    MODEL_CANDIDATE_COMPATIBILITY_FIELDS,
    MODEL_CANDIDATE_PAYLOAD_VERSION,
    MODEL_CANDIDATE_REQUIRED_FIELDS,
    MODEL_CANDIDATE_STRUCTURAL_SHAPE,
)
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.parsing.solution_parser import SolutionParser


def _compiled_prompt(problem_text: str) -> tuple[str, str]:
    problem = ProblemParser().parse(problem_text)
    route = RouterRuleEngine().plan(problem)
    compilation = PrimarySolver().compile_prompt(
        SolverRequest(
            "t5",
            problem,
            route,
            "",
            route.method_families[0],
        )
    )
    return (
        compilation.messages[0]["content"],
        compilation.messages[1]["content"],
    )


@pytest.mark.parametrize(
    ("problem_text", "response_mode", "required_instruction"),
    [
        (
            "Compute 2+2.",
            "answer_only",
            "shortest independently checkable public semantic check",
        ),
        (
            "Show all steps to derive the value of 2+2.",
            "worked_solution",
            "independently checkable complete derivation",
        ),
        (
            "Prove that the square of every real number is nonnegative.",
            "proof_full",
            "proof_steps must contain the complete public proof",
        ),
    ],
)
def test_solver_prompt_explicitly_aligns_public_exposition_to_response_mode(
    problem_text,
    response_mode,
    required_instruction,
):
    system, user = _compiled_prompt(problem_text)

    assert f"Host response mode is {response_mode}." in system
    assert required_instruction in system
    assert f"- Response mode: {response_mode}" in user
    assert "- Answer type:" in user
    assert "standard LaTeX" in system
    assert "JSON-escaped" in system
    assert "hidden chain-of-thought" not in system
    assert system.count("Exact JSON schema example:") == 1
    assert "\\boxed" not in system


def test_model_candidate_payload_has_one_shared_executable_boundary():
    shape = json.loads(MODEL_CANDIDATE_STRUCTURAL_SHAPE)

    assert MODEL_CANDIDATE_PAYLOAD_VERSION == "3.0"
    assert set(shape) == ANSWER_ONLY_CANDIDATE_FIELDS
    assert MODEL_CANDIDATE_COMPATIBILITY_FIELDS == frozenset()

    candidate = SolutionParser().parse(
        json.dumps(
            {
                "final_answer": "4",
                "check": {
                    "statement": "Compute $2+2=4$.",
                    "claim_kind": "equality",
                },
            }
        ),
        candidate_id="shared-contract",
        role="PrimarySolver",
        answer_type="integer",
        planned_method_family="direct-deduction",
        response_mode="answer_only",
    )

    assert candidate.parse_status == "strict_json"
    assert candidate.contract_deviations == []
    assert candidate.public_solution_steps == ["Compute $2+2=4$."]


def test_finalizer_contract_does_not_ask_model_for_host_method_steps():
    from mathforge.agents.registry import PromptContractLoader

    contract = PromptContractLoader().load("finalizer")

    assert contract.fields["output_schema"] == "CompiledFinalizerCandidateProtocol"
    assert "method-step" not in contract.body
    assert '"method_steps":' not in contract.body
