from __future__ import annotations

import pytest

from mathforge.harness.schemas import CandidateSolution
from mathforge.output.deterministic_formatter import DeterministicFormatter
from mathforge.parsing.problem_parser import ProblemParser


def _candidate(answer: str, *, answer_type: str, solution: str) -> CandidateSolution:
    return CandidateSolution(
        "candidate",
        "PrimarySolver",
        "direct-deduction",
        answer,
        answer_type,
        public_solution_steps=[solution],
        solution_text=solution,
    )


@pytest.mark.parametrize(
    ("problem", "answer", "answer_type", "expected"),
    [
        ("计算 $1+1$。", "2", "integer", "2"),
        ("选择正确选项。", "B", "choice", "B"),
        ("判断该命题是否正确。", "正确", "text", "正确"),
        ("填空。", r"\frac{1}{2}", "fraction", r"\frac{1}{2}"),
    ],
)
def test_answer_only_returns_one_latex_answer_line(
    problem,
    answer,
    answer_type,
    expected,
):
    parsed = ProblemParser().parse(problem)
    parsed.answer_type = answer_type
    rendered = DeterministicFormatter().format(
        _candidate(answer, answer_type=answer_type, solution="Hidden exposition."),
        parsed,
    )
    assert rendered == expected
    assert "Hidden exposition" not in rendered


def test_explicit_worked_solution_keeps_steps_out_of_final_response():
    parsed = ProblemParser().parse("计算 $1+1$ 并写出过程。")
    rendered = DeterministicFormatter().format(
        _candidate("2", answer_type="integer", solution="由 $1+1=2$ 可得结果。"),
        parsed,
    )
    assert parsed.response_mode == "worked_solution"
    assert rendered == "2"


def test_proof_full_preserves_complete_public_proof():
    parsed = ProblemParser().parse(r"证明：对任意实数 $x$，$x^2\ge 0$。")
    proof = (
        r"证明：若 $x\ge 0$，则 $x^2\ge 0$；"
        r"若 $x<0$，则 $-x>0$，故 $x^2=(-x)^2\ge 0$。"
        "因此命题成立。$\\square$"
    )
    rendered = DeterministicFormatter().format(
        _candidate("命题成立", answer_type="text", solution=proof),
        parsed,
    )
    assert parsed.response_mode == "proof_full"
    assert rendered.startswith(proof)
    assert rendered.endswith("命题成立")


def test_existing_latex_delimiters_are_not_nested_for_answer_only():
    parsed = ProblemParser().parse("计算表达式。")
    rendered = DeterministicFormatter().format(
        _candidate("$x^2+1$", answer_type="expression", solution="Unused."),
        parsed,
    )
    assert rendered == r"x^2+1"
