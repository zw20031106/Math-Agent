from __future__ import annotations

import pytest

from mathforge.harness.schemas import CandidateSolution
from mathforge.output.answer_validator import AnswerValidator
from mathforge.output.deterministic_formatter import (
    DeterministicFormatter,
    bound_final_response,
)
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
    assert rendered == r"\frac{1}{3}"


def test_final_response_limit_preserves_complete_exact_answer():
    rendered = bound_final_response(
        ("A complete derivation. " * 2000) + "\n\nFinal answer: -1/4",
        exact_answer="-1/4",
        max_chars=20000,
        response_mode="answer_only",
    )

    assert len(rendered) <= 20000
    assert rendered == "-1/4"


def test_formatter_does_not_treat_exact_answer_as_substring_of_wrong_value():
    parsed = ProblemParser().parse("求整数答案")
    candidate = CandidateSolution(
        "c",
        "PrimarySolver",
        "arithmetic",
        "2",
        "integer",
        solution_text="A mistaken derivation concludes 42.",
    )
    rendered = DeterministicFormatter().format(candidate, parsed)
    assert rendered == "2"


def test_formatter_replaces_existing_answer_line_with_one_canonical_block():
    parsed = ProblemParser().parse("求整数答案并写出过程")
    candidate = CandidateSolution(
        "c",
        "PrimarySolver",
        "arithmetic",
        "2",
        "integer",
        solution_text="Work.\nAnswer: 42",
    )
    rendered = DeterministicFormatter().format(candidate, parsed)
    assert "Answer: 42" not in rendered
    assert rendered == "2"


@pytest.mark.parametrize(
    ("problem", "answer", "rendered_answer"),
    [
        ("选择：\nA. 1\nB. 2", "A", "A"),
        ("求分数答案", r"\frac{1}{3}", r"\frac{1}{3}"),
        ("求解集合", "{1,2}", "{1,2}"),
        ("求解区间", "[0,1)", "[0,1)"),
        ("求矩阵", "[[1,0],[0,1]]", "[[1,0],[0,1]]"),
    ],
)
def test_formatter_preserves_exact_answer_representation_in_unique_block(
    problem,
    answer,
    rendered_answer,
):
    parsed = ProblemParser().parse(problem)
    candidate = CandidateSolution(
        "c",
        "PrimarySolver",
        "direct",
        answer,
        parsed.answer_type,
        solution_text="Work.",
    )
    rendered = DeterministicFormatter().format(candidate, parsed)
    assert rendered == rendered_answer


def test_formatter_does_not_double_wrap_existing_latex_delimiters():
    parsed = ProblemParser().parse("求表达式")
    candidate = CandidateSolution(
        "c",
        "PrimarySolver",
        "direct",
        r"$x^2+1$",
        "expression",
        solution_text="Work.",
    )

    rendered = DeterministicFormatter().format(candidate, parsed)

    assert rendered == r"x^2+1"
