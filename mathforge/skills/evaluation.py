from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import math
from typing import Any, Iterable

from mathforge.evaluation.scoring import score_response as score_observed_response


SKILL_BENCHMARK_CASE_TYPES = frozenset(
    {"positive", "negative", "adversarial", "selection", "ablation"}
)


@dataclass(frozen=True)
class SkillBenchmarkCase:
    """A taxonomy-labelled case; correctness still comes from observed runs."""

    case_id: str
    skill_name: str
    case_type: str
    problem: str = ""
    expected_skills: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.case_id).strip() or not str(self.skill_name).strip():
            raise ValueError("SkillBenchmarkCase requires case_id and skill_name")
        if self.case_type not in SKILL_BENCHMARK_CASE_TYPES:
            raise ValueError(f"unsupported Skill benchmark case type: {self.case_type}")
        object.__setattr__(
            self,
            "expected_skills",
            tuple(dict.fromkeys(str(item) for item in self.expected_skills if str(item))),
        )
        object.__setattr__(self, "metadata", dict(self.metadata))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SkillBenchmarkCase":
        if not isinstance(payload, dict):
            raise ValueError("Skill benchmark case must be an object")
        return cls(
            case_id=str(payload.get("case_id", "")),
            skill_name=str(payload.get("skill_name", "")),
            case_type=str(payload.get("case_type", "")),
            problem=str(payload.get("problem", "")),
            expected_skills=tuple(
                str(item)
                for item in payload.get("expected_skills", ())
                if str(item)
            ),
            metadata=payload.get("metadata", {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "skill_name": self.skill_name,
            "case_type": self.case_type,
            "problem": self.problem,
            "expected_skills": list(self.expected_skills),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SkillBenchmarkCoverage:
    skill_name: str
    case_counts: dict[str, int]
    missing_case_types: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.missing_case_types

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "case_counts": dict(self.case_counts),
            "missing_case_types": list(self.missing_case_types),
            "complete": self.complete,
        }


@dataclass(frozen=True)
class SkillSpecificBenchmarkReport:
    coverage: tuple[SkillBenchmarkCoverage, ...]
    ablation: "SkillAblationReport"

    @property
    def complete(self) -> bool:
        return all(item.complete for item in self.coverage)

    @property
    def recommended_action(self) -> str:
        if not self.complete:
            return "collect_missing_cases"
        if self.ablation.accuracy_delta <= 0.0:
            return "downweight_or_disable"
        return "retain_and_monitor"

    def to_dict(self) -> dict[str, Any]:
        return {
            "coverage": [item.to_dict() for item in self.coverage],
            "ablation": self.ablation.to_dict(),
            "complete": self.complete,
            "recommended_action": self.recommended_action,
        }


@dataclass(frozen=True)
class SkillAblationReport:
    evidence_scope: str
    selection_precision: float
    selection_recall: float
    skill_on_accuracy: float
    skill_off_accuracy: float
    accuracy_delta: float
    tokens_added: int
    pair_count: int = 0
    on_scored_count: int = 0
    off_scored_count: int = 0
    on_ci95: tuple[float, float] = (0.0, 0.0)
    off_ci95: tuple[float, float] = (0.0, 0.0)
    failure_strata: dict[str, dict[str, int]] = field(default_factory=dict)
    unpaired_case_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["on_ci95"] = list(self.on_ci95)
        payload["off_ci95"] = list(self.off_ci95)
        payload["unpaired_case_ids"] = list(self.unpaired_case_ids)
        return payload


def evaluate_paired_skill_runs(records: Iterable[dict[str, Any]]) -> SkillAblationReport:
    """Evaluate real ON/OFF runs keyed by case id.

    Each row must contain ``case_id``, ``skill_enabled`` and observable
    ``actual``/``expected`` values (or a ``score`` object containing them).
    Correctness is derived by :func:`score_response`; hand-authored
    ``skill_on_correct``/``skill_off_correct`` labels are deliberately rejected.
    """
    rows = list(records)
    if any(
        key in row
        for row in rows
        for key in ("skill_on_correct", "skill_off_correct")
    ):
        raise ValueError(
            "paired ablation requires observable actual/expected responses; "
            "manual skill_on_correct labels are not accepted"
        )
    by_case: dict[str, dict[bool, dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("paired ablation rows must be objects")
        case_id = str(row.get("case_id", "")).strip()
        if not case_id:
            raise ValueError("paired ablation row requires case_id")
        enabled = row.get("skill_enabled")
        if type(enabled) is not bool:
            raise ValueError("paired ablation row requires boolean skill_enabled")
        modes = by_case.setdefault(case_id, {})
        if enabled in modes:
            raise ValueError(f"duplicate Skill mode for case {case_id}")
        modes[enabled] = dict(row)

    unpaired = tuple(sorted(case_id for case_id, modes in by_case.items() if len(modes) != 2))
    paired = {
        case_id: modes
        for case_id, modes in by_case.items()
        if True in modes and False in modes
    }
    scored: dict[bool, list[dict[str, Any]]] = {True: [], False: []}
    for modes in paired.values():
        for enabled, row in modes.items():
            score = score_response(row)
            scored[enabled].append({**row, **score})

    on_correct = sum(bool(row["correct"]) for row in scored[True])
    off_correct = sum(bool(row["correct"]) for row in scored[False])
    on_scored = sum(not row["unscored"] for row in scored[True])
    off_scored = sum(not row["unscored"] for row in scored[False])
    on_accuracy = on_correct / on_scored if on_scored else 0.0
    off_accuracy = off_correct / off_scored if off_scored else 0.0

    selection_rows = [modes[True] for modes in paired.values()]
    selected = sum(len(_skill_names(row.get("selected"))) for row in selection_rows)
    relevant = sum(
        len(_skill_names(row.get("expected_skills", row.get("expected"))))
        for row in selection_rows
    )
    true_positive = sum(
        len(
            set(_skill_names(row.get("selected")))
            & set(
                _skill_names(
                    row.get("expected_skills", row.get("expected"))
                )
            )
        )
        for row in selection_rows
    )
    tokens_added = sum(
        int(modes[True].get("tokens", modes[True].get("tokens_added", 0)))
        - int(modes[False].get("tokens", modes[False].get("tokens_added", 0)))
        for modes in paired.values()
    )
    return SkillAblationReport(
        evidence_scope="paired_real_runs",
        selection_precision=true_positive / selected if selected else 0.0,
        selection_recall=true_positive / relevant if relevant else 0.0,
        skill_on_accuracy=on_accuracy,
        skill_off_accuracy=off_accuracy,
        accuracy_delta=on_accuracy - off_accuracy,
        tokens_added=tokens_added,
        pair_count=len(paired),
        on_scored_count=on_scored,
        off_scored_count=off_scored,
        on_ci95=_wilson_interval(on_correct, on_scored),
        off_ci95=_wilson_interval(off_correct, off_scored),
        failure_strata={
            "skill_on": _failure_strata(scored[True]),
            "skill_off": _failure_strata(scored[False]),
        },
        unpaired_case_ids=unpaired,
    )


def evaluate_contract_canary(records: Iterable[dict[str, Any]]) -> SkillAblationReport:
    """Compatibility name for the real paired evaluator.

    The previous synthetic canary accepted two manually supplied booleans and
    therefore could not measure model quality.  Callers must now provide two
    observable runs per case.
    """
    return evaluate_paired_skill_runs(records)


def skill_benchmark_coverage(
    cases: Iterable[SkillBenchmarkCase | dict[str, Any]],
    *,
    skill_names: Iterable[str] | None = None,
) -> tuple[SkillBenchmarkCoverage, ...]:
    """Validate positive/negative/adversarial/selection/ablation coverage."""

    normalized = tuple(
        case if isinstance(case, SkillBenchmarkCase) else SkillBenchmarkCase.from_dict(case)
        for case in cases
    )
    names = tuple(
        dict.fromkeys(
            str(name) for name in (skill_names or ()) if str(name).strip()
        )
    ) or tuple(dict.fromkeys(case.skill_name for case in normalized))
    result: list[SkillBenchmarkCoverage] = []
    for name in names:
        counts = {case_type: 0 for case_type in sorted(SKILL_BENCHMARK_CASE_TYPES)}
        for case in normalized:
            if case.skill_name == name:
                counts[case.case_type] += 1
        missing = tuple(
            case_type for case_type in sorted(SKILL_BENCHMARK_CASE_TYPES) if counts[case_type] == 0
        )
        result.append(SkillBenchmarkCoverage(name, counts, missing))
    return tuple(result)


def validate_skill_benchmark_cases(
    cases: Iterable[SkillBenchmarkCase | dict[str, Any]],
    *,
    skill_names: Iterable[str] | None = None,
) -> tuple[SkillBenchmarkCoverage, ...]:
    coverage = skill_benchmark_coverage(cases, skill_names=skill_names)
    incomplete = [item for item in coverage if not item.complete]
    if incomplete:
        details = ", ".join(
            f"{item.skill_name}:missing={','.join(item.missing_case_types)}"
            for item in incomplete
        )
        raise ValueError(f"Skill benchmark coverage incomplete: {details}")
    return coverage


def evaluate_skill_specific_benchmark(
    cases: Iterable[SkillBenchmarkCase | dict[str, Any]],
    records: Iterable[dict[str, Any]],
    *,
    require_complete: bool = True,
) -> SkillSpecificBenchmarkReport:
    normalized_cases = tuple(
        case if isinstance(case, SkillBenchmarkCase) else SkillBenchmarkCase.from_dict(case)
        for case in cases
    )
    coverage = skill_benchmark_coverage(normalized_cases)
    if require_complete:
        incomplete = [item for item in coverage if not item.complete]
        if incomplete:
            details = ", ".join(
                f"{item.skill_name}:missing={','.join(item.missing_case_types)}"
                for item in incomplete
            )
            raise ValueError(f"Skill benchmark coverage incomplete: {details}")
    return SkillSpecificBenchmarkReport(
        coverage=coverage,
        ablation=evaluate_paired_skill_runs(records),
    )


# Short alias for callers that use the task wording.
evaluate_skill_benchmark = evaluate_skill_specific_benchmark


def score_response(row: dict[str, Any]) -> dict[str, Any]:
    """Derive correctness and a failure category from observed run output."""
    score_payload = row.get("score")
    if isinstance(score_payload, dict):
        source = {**row, **score_payload}
    else:
        source = row
    actual = source.get("actual", source.get("actual_response"))
    expected = source.get("expected_answer", source.get("expected_response"))
    if expected is None:
        expected = source.get("expected")
    if actual is None or expected is None:
        return {"correct": False, "unscored": True, "failure_category": "missing_observation"}
    if source.get("status") in {"failed", "timeout", "transport_error"}:
        return {"correct": False, "unscored": True, "failure_category": str(source["status"])}
    answer_type = str(source.get("answer_type", "text"))
    scorer = source.get("scorer")
    actual_text = _answer_text(actual)
    expected_text = _answer_text(expected)
    scored = score_observed_response(
        expected_text,
        actual_text,
        answer_type=answer_type,
        scorer=str(scorer) if scorer else None,
    )
    if not scored.scored or scored.correct is None:
        return {
            "correct": False,
            "unscored": True,
            "failure_category": scored.reason,
        }
    return {
        "correct": bool(scored.correct),
        "unscored": False,
        "failure_category": (
            "correct" if scored.correct else str(source.get("failure_category", scored.reason))
        ),
    }


def _answer_text(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("final_response", "final_answer", "answer"):
            if key in value:
                value = value[key]
                break
    if isinstance(value, (list, tuple)):
        return json.dumps(list(value), ensure_ascii=False)
    return str(value)


def _failure_strata(rows: list[dict[str, Any]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        category = str(row.get("failure_category", "unclassified"))
        result[category] = result.get(category, 0) + 1
    return dict(sorted(result.items()))


def _skill_names(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return ()
    return tuple(str(item) for item in value if str(item).strip())


def _wilson_interval(successes: int, trials: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if trials <= 0:
        return (0.0, 0.0)
    p = successes / trials
    denominator = 1.0 + z * z / trials
    center = (p + z * z / (2.0 * trials)) / denominator
    margin = z * math.sqrt((p * (1.0 - p) / trials) + z * z / (4.0 * trials * trials)) / denominator
    return (max(0.0, center - margin), min(1.0, center + margin))
