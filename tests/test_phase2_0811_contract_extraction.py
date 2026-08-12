from __future__ import annotations

import json

import pytest

from mathforge.agent_runtime.protocol import AgentTurnPayloadParser
from mathforge.agent_runtime.router_protocol import parse_router_intent
from mathforge.evaluation.scoring import extract_final_answer
from mathforge.parsing.answer_extraction import extract_boxed, prepare_model_text
from mathforge.parsing.answer_salvage import salvage_any_answer
from mathforge.parsing.solution_parser import (
    SolutionParser,
    candidate_response_validation,
)
from mathforge.parsing.structured_output import StructuredOutputRecoveryLayer
from mathforge.verification.answer_normalization import unwrap_answer


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (r"42", "42"),
        (r"\frac{1}{2}", r"\frac{1}{2}"),
        (r"\sqrt{1+\sqrt{2}}", r"\sqrt{1+\sqrt{2}}"),
        (r"\text{no solution}", r"\text{no solution}"),
        (
            r"\begin{pmatrix}1&2\\3&4\end{pmatrix}",
            r"\begin{pmatrix}1&2\\3&4\end{pmatrix}",
        ),
    ],
)
def test_shared_boxed_extractor_supports_arbitrary_nested_braces(
    answer: str,
    expected: str,
) -> None:
    response = rf"work \boxed{{{answer}}}"

    assert extract_boxed(response) == [expected]
    normalized_expected = "no solution" if answer.startswith(r"\text") else expected
    assert extract_final_answer(response) == normalized_expected
    assert unwrap_answer(rf"\boxed{{{answer}}}") == normalized_expected


def test_complete_think_is_removed_at_structured_parsing_entry() -> None:
    response = '<think>{"wrong":true}</think>{"answer":4}'
    recovered = StructuredOutputRecoveryLayer().parse_object(response)

    assert recovered.value == {"answer": 4}
    assert prepare_model_text(response).think_truncated is False


def test_router_parser_accepts_closed_think_before_public_json() -> None:
    payload = {
        "primary_domain": "algebra",
        "secondary_domain": None,
        "risk": "medium",
        "patterns": [],
        "preferred_methods": ["substitution-elimination"],
        "alternative_methods": ["factorization-invariant"],
        "needs_long_horizon": True,
    }
    intent, tier, _, _ = parse_router_intent(
        f"<think>routing</think>{json.dumps(payload)}",
        allowed_domains={"algebra"},
    )

    assert intent.primary_domain == "algebra"
    assert tier == "strict_json"


def test_agent_turn_host_field_inside_closed_think_is_ignored() -> None:
    payload = {
        "protocol_version": "1.0",
        "task_result_type": "CheckpointArtifact",
        "action": "abstain",
        "public_state_delta": {},
        "result_payload": {},
        "outbound_intents": [],
        "progress_summary": "No candidate published.",
        "stop_reason": "insufficient proof",
    }
    parsed = AgentTurnPayloadParser().parse(
        f'<think>{{"task_id":"private"}}</think>{json.dumps(payload)}',
        allowed_actions=("abstain",),
    )

    assert parsed.payload.action == "abstain"


def test_unclosed_think_is_answer_salvage_only_and_degraded() -> None:
    raw = r"<think>unfinished derivation; final answer: \boxed{\frac{3}{7}}"
    candidate = SolutionParser().parse(
        raw,
        candidate_id="think-truncated",
        role="PrimarySolver",
        answer_type="fraction",
        planned_method_family="direct-deduction",
    )

    assert candidate.final_answer == r"\frac{3}{7}"
    assert candidate.degraded is True
    assert candidate.solution_text != raw
    assert candidate_response_validation(candidate)[1] is False
    assert salvage_any_answer([raw]) == r"\boxed{\frac{3}{7}}"


def test_two_field_candidate_is_strict_and_host_derives_safe_defaults() -> None:
    candidate = SolutionParser().parse(
        json.dumps(
            {
                "final_answer": r"\boxed{4}",
                "solution_text": "Compute $2+2=4$.",
            }
        ),
        candidate_id="minimal-contract",
        role="PrimarySolver",
        answer_type="integer",
        planned_method_family="direct-deduction",
    )

    assert candidate.final_answer == "4"
    assert candidate.method == "direct-deduction"
    assert candidate.planned_method_family == "direct-deduction"
    assert candidate.public_solution_steps == ["Compute $2+2=4$."]
    assert len(candidate.claims) == 1
    assert candidate.contract_deviations == []
    assert candidate.parse_tier == "strict"


def test_unknown_claim_check_type_is_whitelist_normalized() -> None:
    candidate = SolutionParser().parse(
        json.dumps(
            {
                "final_answer": "4",
                "solution_text": "Compute $2+2=4$.",
                "claims": [
                    {
                        "claim_id": "c1",
                        "statement": "$2+2=4$.",
                        "depends_on": [],
                        "check_type": "invented-check",
                        "importance": "critical",
                    }
                ],
            }
        ),
        candidate_id="normalized-check",
        role="PrimarySolver",
        answer_type="integer",
    )

    assert candidate.claims[0].check_type == "reasoning"
    assert "claims[0].check_type:value" in candidate.contract_deviations
