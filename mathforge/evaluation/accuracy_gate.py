"""可复现的端到端准确率回归门禁。

该模块只负责把固定题集、模型输出和评分器连接起来。它不会把缺失输出、
不可评分输出或未注册的基线静默当成成功，从而避免用内部流程计数冒充数学
准确率。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from math import isfinite
from pathlib import Path
from typing import Any, Iterable, Mapping

from mathforge.evaluation.scoring import ScoreResult, score_response


GOLDEN_SET_SCHEMA_VERSION = "1.0"
DEFAULT_MAX_DROP = 0.02


@dataclass(frozen=True)
class AccuracyCase:
    """固定准确率题集中的一个可自动评分用例。"""

    case_id: str
    problem: str
    expected_answer: str
    answer_type: str
    scorer: str
    problem_type: str = "calculation"
    subject: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AccuracyCase":
        required = ("case_id", "problem", "expected_answer", "answer_type", "scorer")
        missing = [key for key in required if not str(value.get(key, "")).strip()]
        if missing:
            raise ValueError("golden case fields are missing: " + ", ".join(missing))
        return cls(
            case_id=str(value["case_id"]),
            problem=str(value["problem"]),
            expected_answer=str(value["expected_answer"]),
            answer_type=str(value["answer_type"]),
            scorer=str(value["scorer"]),
            problem_type=str(value.get("problem_type", "calculation")),
            subject=str(value.get("subject", "")),
        )


@dataclass(frozen=True)
class AccuracyRegressionReport:
    """一次固定题集回归检查的公开结果。"""

    baseline_accuracy: float
    current_accuracy: float
    delta: float
    max_drop: float
    passed: bool
    total_cases: int
    correct_cases: int
    unscored_case_ids: tuple[str, ...]
    failed_case_ids: tuple[str, ...]
    case_results: tuple[dict[str, Any], ...]

    @property
    def drop_percentage_points(self) -> float:
        return max(0.0, -self.delta) * 100.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {
            "unscored_case_ids": list(self.unscored_case_ids),
            "failed_case_ids": list(self.failed_case_ids),
            "drop_percentage_points": self.drop_percentage_points,
            "case_results": list(self.case_results),
        }


def load_golden_set(path: str | Path) -> list[AccuracyCase]:
    """读取固定 JSONL 题集并拒绝重复或空题集。"""

    source = Path(path)
    cases: list[AccuracyCase] = []
    for line_number, line in enumerate(
        source.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid golden JSONL at line {line_number}") from error
        if not isinstance(value, dict):
            raise ValueError(f"golden case at line {line_number} is not an object")
        cases.append(AccuracyCase.from_mapping(value))
    if not cases:
        raise ValueError("golden set must not be empty")
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("golden set case_id values must be unique")
    return cases


def evaluate_accuracy_regression(
    cases: Iterable[AccuracyCase],
    responses: Mapping[str, str],
    *,
    baseline_accuracy: float,
    max_drop: float = DEFAULT_MAX_DROP,
) -> AccuracyRegressionReport:
    """按总题数计算准确率，并在下降超过阈值时失败。

    题目缺少响应、评分器返回 ``scored=False`` 或返回错误，均属于门禁失败，
    不允许通过改变分母掩盖失败。
    """

    if not isfinite(baseline_accuracy) or not 0.0 <= baseline_accuracy <= 1.0:
        raise ValueError("baseline_accuracy must be between 0 and 1")
    if not isfinite(max_drop) or not 0.0 <= max_drop <= 1.0:
        raise ValueError("max_drop must be between 0 and 1")

    materialized = list(cases)
    if not materialized:
        raise ValueError("accuracy regression requires at least one case")
    results: list[dict[str, Any]] = []
    unscored: list[str] = []
    failed: list[str] = []
    correct = 0
    for case in materialized:
        response_present = case.case_id in responses
        response = responses.get(case.case_id, "")
        score: ScoreResult = score_response(
            case.expected_answer,
            response,
            answer_type=case.answer_type,
            scorer=case.scorer,
        )
        if score.scored and score.correct is True:
            correct += 1
        else:
            failed.append(case.case_id)
        if not response_present or not score.scored:
            unscored.append(case.case_id)
        results.append(
            {
                "case_id": case.case_id,
                "scored": score.scored,
                "correct": score.correct,
                "reason": score.reason,
                "scorer": score.scorer,
            }
        )

    current = correct / len(materialized)
    delta = current - baseline_accuracy
    passed = not unscored and delta + 1e-12 >= -max_drop
    return AccuracyRegressionReport(
        baseline_accuracy=baseline_accuracy,
        current_accuracy=current,
        delta=delta,
        max_drop=max_drop,
        passed=passed,
        total_cases=len(materialized),
        correct_cases=correct,
        unscored_case_ids=tuple(unscored),
        failed_case_ids=tuple(failed),
        case_results=tuple(results),
    )


__all__ = [
    "AccuracyCase",
    "AccuracyRegressionReport",
    "DEFAULT_MAX_DROP",
    "GOLDEN_SET_SCHEMA_VERSION",
    "evaluate_accuracy_regression",
    "load_golden_set",
]
