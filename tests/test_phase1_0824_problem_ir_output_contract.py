from __future__ import annotations

import json

from mathforge.agents.router_planner import RouterPlanner
from mathforge.harness.schemas import CandidateSolution, ProblemIR
from mathforge.harness.terminalizer import MINIMAL_FALLBACK_RESPONSE
from mathforge.output.deterministic_formatter import DeterministicFormatter
from mathforge.parsing.problem_parser import ProblemParser


def _router_payload() -> str:
    return json.dumps(
        {
            "primary_domain": "general-math",
            "secondary_domain": None,
            "risk": "high",
            "patterns": ["ambiguous-target"],
            "preferred_methods": ["direct-deduction"],
            "alternative_methods": ["constructive-computation"],
            "needs_long_horizon": True,
        }
    )


def test_inline_choice_scanner_preserves_stem_conditions_and_all_options() -> None:
    raw = (
        r"Given $x>0$ and $x^2=4$, which of the following is $x$? "
        r"A. $-2$ B. $0$ C. $2$ D. $4$"
    )

    problem = ProblemParser().parse(raw)

    assert problem.problem_type == "multiple_choice"
    assert problem.answer_type == "choice"
    assert problem.options == ["$-2$", "$0$", "$2$", "$4$"]
    assert "x>0" in problem.normalized_problem
    assert "x^2=4" in problem.normalized_problem
    assert problem.raw_problem == raw
    assert "which of the following" in problem.requested_output.lower()


def test_inline_chinese_choice_scanner_handles_full_width_labels() -> None:
    problem = ProblemParser().parse(
        "设实数 x 满足 x>0，下列结论正确的是：（A）x>0 （B）x<0 （C）x=0"
    )

    assert problem.options == ["x>0", "x<0", "x=0"]
    assert problem.target_kind == "select_option"


def test_choice_scanner_does_not_promote_line_leading_prose() -> None:
    problem = ProblemParser().parse(
        "A finite graph is connected.\nB vertices may have odd degree.\n"
        "Prove that the number of odd-degree vertices is even."
    )

    assert problem.problem_type == "proof"
    assert problem.options == []


def test_problem_ir_round_trip_exposes_interpretation_confidence_and_conflicts() -> None:
    problem = ProblemParser().parse(
        "Find all real x satisfying x^2=1.",
        metadata={"answer_type": "integer", "response_mode": "proof_full"},
    )
    payload = problem.to_dict()
    restored = ProblemIR.from_dict(payload)

    assert 0.0 <= restored.target_confidence <= 1.0
    assert 0.0 <= restored.answer_type_confidence <= 1.0
    assert 0.0 <= restored.response_mode_confidence <= 1.0
    assert restored.interpretation_conflicts
    assert restored.requires_router_disambiguation is True
    json.dumps(payload, ensure_ascii=False, allow_nan=False)


def test_low_confidence_router_receives_exact_full_problem_and_conflict_context() -> None:
    raw = "Find all real x∈ℝ satisfying x^2=1; return the requested object."
    problem = ProblemParser().parse(raw)
    captured: dict[str, object] = {}

    def chat(**kwargs):
        captured.update(kwargs)
        return _router_payload()

    outcome = RouterPlanner().plan_authoritative(
        problem,
        llm_chat=chat,
        consume_call=lambda: None,
        max_tokens=1024,
    )

    prompt = "\n".join(
        message["content"] for message in captured["messages"]  # type: ignore[index]
    )
    assert outcome.source == "llm_router"
    assert problem.requires_router_disambiguation is True
    assert raw in prompt
    assert "Parser interpretation requiring disambiguation" in prompt
    assert "answer_type_confidence" in prompt


def test_public_response_profiles_are_canonical_and_json_serializable() -> None:
    direct = ProblemParser().parse("Compute 2+2 and show your work.")
    direct_candidate = CandidateSolution(
        "c1",
        "PrimarySolver",
        "direct",
        r"\boxed{4}",
        direct.answer_type,
        solution_text="First add the two integers.\nAnswer: 4",
    )
    proof = ProblemParser().parse("Prove that the sum of two even integers is even.")
    proof_candidate = CandidateSolution(
        "c2",
        "PrimarySolver",
        "direct",
        "The sum is even.",
        proof.answer_type,
        solution_text=(
            "Let the integers be $2a$ and $2b$.\n"
            "Their sum is $2a+2b=2(a+b)$, hence it is even."
        ),
    )

    direct_response = DeterministicFormatter().format(direct_candidate, direct)
    proof_response = DeterministicFormatter().format(proof_candidate, proof)

    assert direct_response == "4"
    assert "2a+2b=2(a+b)" in proof_response
    assert proof_response.endswith("The sum is even.")
    json.dumps(
        {"final_response": direct_response, "trace": []},
        ensure_ascii=False,
        allow_nan=False,
    )
    assert MINIMAL_FALLBACK_RESPONSE == "0"
