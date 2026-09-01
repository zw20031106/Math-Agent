from __future__ import annotations

from pathlib import Path
import json

from mathforge.evaluation.accuracy_gate import (
    evaluate_accuracy_regression,
    load_golden_set,
)
from scripts.check_accuracy_regression import _load_responses


ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "data" / "evidence" / "local88" / "golden30.jsonl"


def test_local88_golden_set_is_fixed_and_covers_multiple_domains() -> None:
    cases = load_golden_set(GOLDEN)

    assert len(cases) == 30
    assert {case.subject for case in cases} >= {"数学分析", "高等代数", "概率论", "抽象代数"}
    assert {case.scorer for case in cases} >= {"symbolic", "integer", "tuple", "interval"}
    assert [case.case_id for case in cases] == [f"local88-golden-{index:02d}" for index in range(30)]


def test_accuracy_gate_passes_complete_ground_truth_responses() -> None:
    cases = load_golden_set(GOLDEN)
    responses = {case.case_id: case.expected_answer for case in cases}

    report = evaluate_accuracy_regression(
        cases,
        responses,
        baseline_accuracy=1.0,
    )

    assert report.passed
    assert report.current_accuracy == 1.0
    assert report.failed_case_ids == ()
    assert report.unscored_case_ids == ()


def test_accuracy_gate_fails_when_drop_exceeds_two_percentage_points() -> None:
    cases = load_golden_set(GOLDEN)
    responses = {case.case_id: case.expected_answer for case in cases}
    responses[cases[0].case_id] = "明显错误"

    report = evaluate_accuracy_regression(
        cases,
        responses,
        baseline_accuracy=1.0,
        max_drop=0.02,
    )

    assert report.current_accuracy == 29 / 30
    assert report.drop_percentage_points > 2.0
    assert not report.passed
    assert report.failed_case_ids == (cases[0].case_id,)


def test_accuracy_gate_does_not_hide_missing_or_unscored_responses() -> None:
    cases = load_golden_set(GOLDEN)
    responses = {case.case_id: case.expected_answer for case in cases[:-1]}

    report = evaluate_accuracy_regression(
        cases,
        responses,
        baseline_accuracy=0.0,
        max_drop=1.0,
    )

    assert report.unscored_case_ids == (cases[-1].case_id,)
    assert report.failed_case_ids[-1] == cases[-1].case_id
    assert not report.passed


def test_accuracy_cli_can_consume_public_case_output_directory(tmp_path: Path) -> None:
    (tmp_path / "case-a.json").write_text(
        json.dumps({"id": "case-a", "status": "success", "final_response": "42", "trace": []}),
        encoding="utf-8",
    )
    (tmp_path / "run_manifest.json").write_text(json.dumps({"case_count": 1}), encoding="utf-8")

    assert _load_responses(tmp_path) == {"case-a": "42"}
