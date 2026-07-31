from __future__ import annotations

import json

import pytest

from mathforge.agents.router_planner import RouterRuleEngine
from mathforge.agents.solver import PrimarySolver, SolverRequest
from mathforge.harness.model_candidate_contract import (
    MODEL_CANDIDATE_COMPATIBILITY_FIELDS,
    MODEL_CANDIDATE_PAYLOAD_VERSION,
    MODEL_CANDIDATE_REQUIRED_FIELDS,
    MODEL_CANDIDATE_STRUCTURAL_SHAPE,
    MODEL_CLAIM_FIELDS,
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
            "1-4 concise, independently checkable steps for trace[0]",
        ),
        (
            "Show all steps to derive the value of 2+2.",
            "worked_solution",
            "complete derivation requested by the problem",
        ),
        (
            "Prove that the square of every real number is nonnegative.",
            "proof_full",
            "complete proof suitable for the final response",
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
    assert "delimit every mathematical formula with $...$" in system
    assert "final_answer as LaTeX source without $ delimiters" in system
    assert "private reasoning, scratchpads, or hidden chain-of-thought" in system


def test_model_candidate_payload_has_one_shared_executable_boundary():
    shape = json.loads(MODEL_CANDIDATE_STRUCTURAL_SHAPE)

    assert MODEL_CANDIDATE_PAYLOAD_VERSION == "2.1"
    assert set(shape) == MODEL_CANDIDATE_REQUIRED_FIELDS
    assert set(shape["claims"][0]) == MODEL_CLAIM_FIELDS
    assert MODEL_CANDIDATE_COMPATIBILITY_FIELDS == {"method_steps"}

    candidate = SolutionParser().parse(
        json.dumps(
            {
                **shape,
                "method": "direct-deduction",
                "final_answer": "4",
                "public_solution_steps": ["Compute $2+2=4$."],
                "solution_text": "Compute $2+2=4$.",
                "claims": [
                    {
                        "claim_id": "c1",
                        "statement": "$2+2=4$.",
                        "depends_on": [],
                        "check_type": "reasoning",
                        "importance": "critical",
                    }
                ],
            }
        ),
        candidate_id="shared-contract",
        role="PrimarySolver",
        answer_type="integer",
    )

    assert candidate.parse_status == "strict_json"
    assert candidate.contract_deviations == []
    assert candidate.public_solution_steps == ["Compute $2+2=4$."]


def test_finalizer_contract_does_not_ask_model_for_host_method_steps():
    from mathforge.agents.registry import PromptContractLoader

    contract = PromptContractLoader().load("finalizer")

    assert contract.fields["output_schema"] == "ModelCandidatePayloadV2.1"
    assert "`method_steps`" in contract.body
    assert '"method_steps":' not in contract.body
