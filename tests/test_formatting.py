from __future__ import annotations

import pytest

from mathforge.harness.schemas import CandidateSolution
from mathforge.output.answer_validator import AnswerValidator
from mathforge.output.deterministic_formatter import DeterministicFormatter
from mathforge.parsing.problem_parser import ProblemParser


@pytest.mark.parametrize(
    ("problem", "answer"),
    [
        ("求整数答案", "2"),
        ("求分数答案", "1/3"),
        ("求表达式", "x^2+1"),
        ("求解集合", "{1,2}"),
        ("求解区间", "[0,1)"),
        ("求矩阵", "[[1,0],[0,1]]"),
        ("选择：\nA. 1\nB. 2", "A"),
    ],
)
def test_answer_types_accept_expected_forms(problem, answer):
    parsed = ProblemParser().parse(problem)
    candidate = CandidateSolution("c", "PrimarySolver", "test", answer, parsed.answer_type)
    assert AnswerValidator().validate(candidate, parsed) == []


def test_formatter_preserves_exact_answer():
    parsed = ProblemParser().parse("求分数答案")
    candidate = CandidateSolution(
        "c", "PrimarySolver", "algebra", r"\frac{1}{3}", "fraction", solution_text="Derivation"
    )
    rendered = DeterministicFormatter().format(candidate, parsed)
    assert rendered.endswith(r"\frac{1}{3}")
