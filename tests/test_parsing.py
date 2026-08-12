from __future__ import annotations

import pytest

from mathforge.parsing.problem_parser import ProblemParser
from mathforge.parsing.solution_parser import SolutionParser


@pytest.mark.parametrize(
    ("problem", "expected"),
    [
        ("选择正确结论：\nA. 1\nB. 2", "multiple_choice"),
        ("填空：1+1=____", "fill_blank"),
        ("计算 2+2。", "calculation"),
        ("推导二项式定理。", "derivation"),
        ("证明 x^2 >= 0。", "proof"),
        ("解释为什么该极限存在。", "explanation"),
    ],
)
def test_problem_types(problem, expected):
    assert ProblemParser().parse(problem).problem_type == expected


def test_problem_parser_extracts_options_domains_and_normalizes_unicode():
    parsed = ProblemParser().parse("设 x ∈ \\mathbb{R} 且 x≥0。\nA. x\nB. −x")
    assert parsed.options == ["x", "-x"]
    assert parsed.domains == {"x": r"\mathbb{R}"}
    assert r"\ge" in parsed.normalized_problem


def test_solution_parser_degradation_chain():
    parser = SolutionParser()
    strict = parser.parse(
        '{"method":"algebra","solution_text":"work","final_answer":"1/2"}',
        candidate_id="c1",
        role="PrimarySolver",
        answer_type="fraction",
    )
    assert strict.parse_status == "strict_json"
    assert strict.contract_deviations == []
    assert strict.final_answer == "1/2"
    outer = parser.parse(
        'Result follows. {"final_answer":"4","solution_text":"work"} done',
        candidate_id="c2",
        role="PrimarySolver",
        answer_type="integer",
    )
    assert outer.parse_status == "outer_json"
    regex = parser.parse(
        "Reasoning here.\nFinal answer: 7",
        candidate_id="c3",
        role="PrimarySolver",
        answer_type="integer",
    )
    assert regex.parse_status == "regex_answer"
    assert regex.final_answer == "7"
