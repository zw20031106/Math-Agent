from __future__ import annotations

import json
from pathlib import Path

import pytest

from mathforge.benchmark import (
    load_jsonl,
    preflight_benchmark_cases,
    run_benchmark,
)
from mathforge.config import HarnessConfig
from mathforge.evaluation.scoring import score_response
from mathforge.harness.schemas import ProblemIR, SchemaValidationError
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.runtime import MathForgeHarness
from tests.fake_client import FakeClient


GOLD_DATASET = (
    Path(__file__).resolve().parents[1] / "data" / "dev_set_2_gold.jsonl"
)
PARSER_COUNTEREXAMPLE_IDS = {
    "10",
    "11",
    "12",
    "13",
    "15",
    "17",
    "49",
    "60",
    "63",
    "64",
    "68",
    "69",
    "74",
    "75",
    "76",
    "81",
    "83",
    "86",
    "87",
}


def test_88_case_gold_dataset_has_complete_parser_and_scoring_facts():
    cases = load_jsonl(GOLD_DATASET)
    parser = ProblemParser()
    mismatches = []
    for case in cases:
        parsed = parser.parse(case.problem)
        if (
            parsed.problem_type != case.problem_type
            or parsed.answer_type != case.answer_type
        ):
            mismatches.append(
                (
                    case.idx,
                    case.problem_type,
                    parsed.problem_type,
                    case.answer_type,
                    parsed.answer_type,
                )
            )
        assert parsed.target_phrase
        assert parsed.parser_confidence >= 0.7

    assert len(cases) == 88
    assert mismatches == []
    preflight = preflight_benchmark_cases(cases)
    assert preflight.expected_count == 88
    assert preflight.invalid_expected_count == 0
    assert preflight.auto_scored_count == 88
    assert preflight.manual_count == 0
    assert preflight.auto_score_coverage == 1.0


def test_all_19_reproduced_target_misclassifications_are_fixed():
    cases = {
        case.idx: case
        for case in load_jsonl(GOLD_DATASET)
        if case.idx in PARSER_COUNTEREXAMPLE_IDS
    }
    parser = ProblemParser()

    assert set(cases) == PARSER_COUNTEREXAMPLE_IDS
    assert {
        case_id: parser.parse(case.problem).answer_type
        for case_id, case in cases.items()
    } == {
        case_id: case.answer_type
        for case_id, case in cases.items()
    }
    assert parser.parse(
        "两解释变量均已中心化，且 X^T X 为给定矩阵。求斜率向量。"
    ).problem_type == "calculation"
    assert parser.parse(
        "首次离开区间 (-1,2) 的时刻为 tau。求 E tau。"
    ).answer_type == "expression"
    assert parser.parse(
        "整数同调群由题设定义。求第一整数同调群。"
    ).answer_type == "algebraic_structure"


def test_benchmark_loader_accepts_answer_alias_and_rejects_conflicts(tmp_path):
    alias_path = tmp_path / "alias.jsonl"
    alias_path.write_text(
        json.dumps(
            {
                "idx": 1,
                "problem": "计算 1+1。",
                "answer": "2",
                "answer_type": "integer",
                "scorer": "integer",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    assert load_jsonl(alias_path)[0].expected_answer == "2"

    conflict_path = tmp_path / "conflict.jsonl"
    conflict_path.write_text(
        json.dumps(
            {
                "idx": 1,
                "problem": "计算 1+1。",
                "answer": "2",
                "expected_answer": "3",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="conflicting expected_answer"):
        load_jsonl(conflict_path)


def test_gold_dataset_produces_88_expected_and_full_auto_score_summary():
    cases = load_jsonl(GOLD_DATASET)
    expected_by_id = {case.idx: case.expected_answer for case in cases}

    _, summary = run_benchmark(
        cases,
        lambda _problem, metadata: {
            "final_response": (
                f"Final answer: {expected_by_id[str(metadata['idx'])]}"
            ),
            "trace": [],
        },
    )

    assert summary["expected_count"] == 88
    assert summary["scored_count"] == 88
    assert summary["invalid_expected_count"] == 0
    assert summary["auto_score_coverage"] == 1.0
    assert summary["accuracy"] == 1.0


@pytest.mark.parametrize(
    ("expected", "actual", "answer_type", "scorer"),
    [
        (
            r"-\frac{\pi^2}{8}\ln2+\frac7{16}\zeta(3)",
            r"-pi^2*log(2)/8+7*zeta(3)/16",
            "expression",
            "symbolic",
        ),
        (
            r"3\sqrt[3]{2}/2",
            "3*2^(1/3)/2",
            "expression",
            "symbolic",
        ),
        ("(0,e^{\\pi/2})^T", "(0, exp(pi/2))", "vector", "vector"),
        ("4,3,1", "(4, 3, 1)", "tuple", "tuple"),
        (
            r"\mathbb Z^2\oplus\mathbb Z/2\mathbb Z",
            r"Z^2 \oplus Z/2Z",
            "algebraic_structure",
            "algebraic_structure",
        ),
    ],
)
def test_expanded_scorers_accept_safe_equivalent_forms(
    expected,
    actual,
    answer_type,
    scorer,
):
    result = score_response(
        expected,
        f"Final answer: {actual}",
        answer_type=answer_type,
        scorer=scorer,
    )
    assert result.scored is True
    assert result.correct is True


def test_invalid_actual_answers_have_stable_specific_reasons():
    syntax = score_response(
        "2",
        "Final answer: (",
        answer_type="expression",
    )
    unsafe = score_response(
        "2",
        "Final answer: unknown(2)",
        answer_type="expression",
    )
    vector = score_response(
        "(1,2)",
        "Final answer: not-a-vector",
        answer_type="vector",
    )

    assert syntax.reason == "invalid_actual_syntax"
    assert unsafe.reason == "invalid_actual_unsafe_expression"
    assert vector.reason == "invalid_actual_vector"
    assert all(result.error is False for result in (syntax, unsafe, vector))


@pytest.mark.parametrize(
    ("expected", "response"),
    [
        (
            r"-6+\pi^2/3+2\zeta(3)",
            r"Final answer: \frac{\pi^{2}}{3}+2\zeta(3)-6",
        ),
        (
            r"8\pi^6/63",
            "Final answer: 8π^6/63",
        ),
        (
            r"\lambda^3-2\lambda^2-\lambda-4",
            "Final answer: λ^3 - 2 λ^2 - λ - 4",
        ),
        (
            r"-\frac{\pi^2}{8}\ln2+\frac7{16}\zeta(3)",
            (
                r"Final answer: \frac{7}{16}\zeta(3)"
                r"-\frac{\pi^{2}}{8}\ln 2"
            ),
        ),
    ],
)
def test_live_model_latex_and_unicode_forms_score_symbolically(
    expected,
    response,
):
    result = score_response(
        expected,
        response,
        answer_type="expression",
        scorer="symbolic",
    )

    assert result.correct is True
    assert result.reason == "symbolic_equivalent"


def test_runtime_trace_records_parser_target_and_confidence():
    config = HarnessConfig(
        profile="test",
        status="test",
        max_model_calls=1,
        enable_router=False,
        enable_skills=False,
        enable_alternatives=False,
        enable_tools=False,
        enable_evidence=False,
        enable_proof_obligations=False,
        enable_verifier=False,
        enable_memory=False,
        enable_lemma_loop=False,
        enable_rag=False,
        enable_repair=False,
        enable_finalizer=False,
    )
    result = MathForgeHarness(FakeClient(), config).solve(
        "给定一个矩阵 A。求 det(A)。",
        {},
    )
    parsed = next(
        event for event in result["trace"] if event["event"] == "problem_parsed"
    )

    assert parsed["answer_type"] == "expression"
    assert parsed["target_phrase"] == "求 det(A)"
    assert parsed["parser_confidence"] >= 0.7


def test_problem_ir_rejects_string_parser_confidence():
    payload = ProblemParser().parse("计算 1+1。").to_dict()
    payload["parser_confidence"] = "0.98"

    with pytest.raises(SchemaValidationError, match="parser_confidence"):
        ProblemIR.from_dict(payload)
