"""Fail-closed Phase S5 Skill benchmark and ablation helpers.

The selection benchmark is deterministic and may run offline.  Accuracy and
token claims are intentionally computed only when paired observed model rows
are supplied; the absence of those rows is represented as ``pending_real_runs``
instead of being filled with a fake client or hand-authored correctness.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from mathforge.harness.schemas import ProblemIR
from mathforge.skills.evaluation import (
    SKILL_BENCHMARK_CASE_TYPES,
    SkillBenchmarkCase,
    evaluate_skill_specific_benchmark,
    skill_benchmark_coverage,
    validate_skill_benchmark_cases,
)
from mathforge.skills.registry import SkillRegistry
from mathforge.skills.selector import DynamicSkillSelector


S5_SCHEMA_VERSION = "1.0"
S5_CASE_TYPES = tuple(sorted(SKILL_BENCHMARK_CASE_TYPES))
S5_DEFAULT_CASE_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "skill_s5_benchmark.json"
)
S5_SKILL_NAMES = (
    "dominated-convergence",
    "uniform-convergence",
    "lhopital-limit",
    "epsilon-delta",
    "taylor-remainder",
    "branch-cut-integral",
    "argument-principle",
    "rouche-zero-count",
    "residue-theorem",
    "jordan-form",
    "spectral-theorem",
    "eigenvalue-diagonalization",
    "conditional-expectation",
    "strategy-progress-assessment",
    "root-finding",
    "proof-strategy-selection",
    "mathematical-induction",
    "contradiction-contrapositive",
    "existence-uniqueness",
    "case-split-wlog",
    "proof-theory",
    "lean-proof-workflow",
)
_EXPECTATIONS = frozenset({"include", "exclude", "deprioritize"})


@dataclass(frozen=True)
class SelectionObservation:
    case_id: str
    skill_name: str
    case_type: str
    expectation: str
    selected: tuple[str, ...]
    target_rank: int | None
    passed: bool
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["selected"] = list(self.selected)
        payload["reasons"] = list(self.reasons)
        return payload


@dataclass(frozen=True)
class SelectionBenchmarkReport:
    schema_version: str
    case_count: int
    passed_count: int
    case_type_counts: dict[str, dict[str, int]]
    skill_counts: dict[str, dict[str, int]]
    positive_recall: float
    negative_deprioritization_rate: float
    selection_pass_rate: float
    failures: tuple[dict[str, Any], ...] = ()
    observations: tuple[SelectionObservation, ...] = ()

    @property
    def passed(self) -> bool:
        return self.case_count > 0 and not self.failures

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "case_count": self.case_count,
            "passed_count": self.passed_count,
            "passed": self.passed,
            "case_type_counts": {
                key: dict(value) for key, value in self.case_type_counts.items()
            },
            "skill_counts": {
                key: dict(value) for key, value in self.skill_counts.items()
            },
            "positive_recall": self.positive_recall,
            "negative_deprioritization_rate": self.negative_deprioritization_rate,
            "selection_pass_rate": self.selection_pass_rate,
            "failures": [dict(item) for item in self.failures],
            "observations": [item.to_dict() for item in self.observations],
        }


def load_s5_cases(
    path: Path | str = S5_DEFAULT_CASE_PATH,
    *,
    registry: SkillRegistry | None = None,
) -> tuple[SkillBenchmarkCase, ...]:
    """Load and fail closed on the versioned S5 taxonomy corpus."""

    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("S5 benchmark must be a JSON object")
    if str(payload.get("schema_version", "")) != S5_SCHEMA_VERSION:
        raise ValueError("unsupported S5 benchmark schema version")
    declared = tuple(dict.fromkeys(str(item) for item in payload.get("skills", ())))
    if declared != S5_SKILL_NAMES:
        raise ValueError("S5 benchmark skill list does not match the modified catalog")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list):
        raise ValueError("S5 benchmark cases must be a list")
    cases = tuple(SkillBenchmarkCase.from_dict(item) for item in raw_cases)
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("S5 benchmark contains duplicate case_id")
    unknown = sorted({case.skill_name for case in cases} - set(declared))
    if unknown:
        raise ValueError(f"S5 benchmark contains unknown skills: {unknown}")
    for case in cases:
        expectation = str(case.metadata.get("expectation", "")).strip().casefold()
        if expectation not in _EXPECTATIONS:
            raise ValueError(
                f"{case.case_id} must declare expectation include/exclude/deprioritize"
            )
    validate_skill_benchmark_cases(cases, skill_names=declared)
    if registry is not None:
        missing = sorted(set(declared) - set(registry.names()))
        if missing:
            raise ValueError(f"S5 benchmark skills absent from registry: {missing}")
    return cases


def s5_case_fingerprint(path: Path | str = S5_DEFAULT_CASE_PATH) -> str:
    """Hash the exact benchmark input used by a S5 run."""

    return sha256(Path(path).read_bytes()).hexdigest()


def run_selection_benchmark(
    cases: Iterable[SkillBenchmarkCase],
    *,
    registry: SkillRegistry | None = None,
    role: str = "PrimarySolver",
    top_k: int = 3,
    max_chars: int = 12000,
) -> SelectionBenchmarkReport:
    """Run positive/negative/adversarial/selection routing without a model.

    ``deprioritize`` is deliberately weaker than ``exclude`` because current
    negative-trigger metadata is a bounded rank penalty, not a hard veto.
    """

    values = tuple(cases)
    if top_k < 1 or max_chars < 1:
        raise ValueError("S5 selection limits must be positive")
    catalog = registry or SkillRegistry()
    selector = DynamicSkillSelector(catalog, top_k=top_k)
    observations: list[SelectionObservation] = []
    failures: list[dict[str, Any]] = []
    type_counts: dict[str, Counter[str]] = defaultdict(Counter)
    skill_counts: dict[str, Counter[str]] = defaultdict(Counter)

    for case in values:
        metadata = case.metadata
        problem = _problem_ir(case)
        route_seeds = tuple(
            str(item)
            for item in metadata.get("route_skill_names", ())
            if str(item).strip()
        )
        composition = selector.compose_for_role(
            problem,
            role=role,
            route_skill_names=route_seeds,
            max_chars=max_chars,
            selection_context=f"s5:{case.case_type}",
        )
        selected = tuple(item.name for item in composition.included)
        target_rank = selected.index(case.skill_name) + 1 if case.skill_name in selected else None
        expectation = str(metadata["expectation"]).strip().casefold()
        passed = _expectation_passes(expectation, target_rank)
        reasons = _selection_reasons(composition, case.skill_name)
        observation = SelectionObservation(
            case_id=case.case_id,
            skill_name=case.skill_name,
            case_type=case.case_type,
            expectation=expectation,
            selected=selected,
            target_rank=target_rank,
            passed=passed,
            reasons=reasons,
        )
        observations.append(observation)
        type_counts[case.case_type]["total"] += 1
        type_counts[case.case_type]["passed"] += int(passed)
        skill_counts[case.skill_name]["total"] += 1
        skill_counts[case.skill_name]["passed"] += int(passed)
        if not passed:
            failures.append(
                {
                    "case_id": case.case_id,
                    "skill_name": case.skill_name,
                    "case_type": case.case_type,
                    "expectation": expectation,
                    "selected": list(selected),
                    "target_rank": target_rank,
                    "reasons": list(reasons),
                }
            )

    include = [item for item in observations if item.expectation == "include"]
    deprioritize = [
        item for item in observations if item.expectation == "deprioritize"
    ]
    passed_count = sum(item.passed for item in observations)
    return SelectionBenchmarkReport(
        schema_version=S5_SCHEMA_VERSION,
        case_count=len(observations),
        passed_count=passed_count,
        case_type_counts={
            key: {"total": value["total"], "passed": value["passed"]}
            for key, value in sorted(type_counts.items())
        },
        skill_counts={
            key: {"total": value["total"], "passed": value["passed"]}
            for key, value in sorted(skill_counts.items())
        },
        positive_recall=(
            sum(item.passed for item in include) / len(include) if include else 0.0
        ),
        negative_deprioritization_rate=(
            sum(item.passed for item in deprioritize) / len(deprioritize)
            if deprioritize
            else 0.0
        ),
        selection_pass_rate=(passed_count / len(observations) if observations else 0.0),
        failures=tuple(failures),
        observations=tuple(observations),
    )


def evaluate_s5_ablation(
    cases: Iterable[SkillBenchmarkCase],
    records: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Evaluate paired observed ON/OFF rows or report a fail-closed pending state."""

    values = tuple(cases)
    required_ids = {case.case_id for case in values}
    if records is None:
        return {
            "schema_version": S5_SCHEMA_VERSION,
            "status": "pending_real_runs",
            "evidence_scope": "none",
            "reason": "paired real-model ON/OFF rows were not supplied",
            "required_case_count": len(values),
            "required_row_count": len(values) * 2,
            "accuracy_claim": "blocked",
        }
    rows = [dict(row) for row in records]
    observed_ids = {str(row.get("case_id", "")).strip() for row in rows}
    if observed_ids != required_ids:
        missing = sorted(required_ids - observed_ids)
        extra = sorted(observed_ids - required_ids)
        raise ValueError(
            f"S5 ablation case IDs mismatch; missing={missing}, extra={extra}"
        )
    report = evaluate_skill_specific_benchmark(values, rows, require_complete=True)
    return {
        "schema_version": S5_SCHEMA_VERSION,
        "status": "observed_paired_runs",
        "evidence_scope": report.ablation.evidence_scope,
        "accuracy_claim": "derived_from_observed_actual_expected",
        "report": report.to_dict(),
    }


def run_s5_benchmark(
    path: Path | str = S5_DEFAULT_CASE_PATH,
    *,
    ablation_records: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the complete offline S5 selection audit and optional ablation."""

    registry = SkillRegistry()
    cases = load_s5_cases(path, registry=registry)
    selection = run_selection_benchmark(cases, registry=registry)
    return {
        "schema_version": S5_SCHEMA_VERSION,
        "suite": "S5",
        "case_fingerprint": s5_case_fingerprint(path),
        "skill_fingerprint": registry.fingerprint,
        "skill_count": len(registry.names()),
        "v3_skill_count": sum(
            registry.definition(name).version == "3.0" for name in registry.names()
        ),
        "case_count": len(cases),
        "coverage": [item.to_dict() for item in skill_benchmark_coverage(cases, skill_names=S5_SKILL_NAMES)],
        "selection": selection.to_dict(),
        "ablation": evaluate_s5_ablation(cases, ablation_records),
        "claim_policy": {
            "selection": "offline deterministic selector evidence",
            "accuracy": "blocked until paired observed real-model ON/OFF rows",
            "negative_trigger": "deprioritize is a rank expectation, not a hard veto",
        },
    }


def _problem_ir(case: SkillBenchmarkCase) -> ProblemIR:
    metadata = case.metadata
    problem_type = str(metadata.get("problem_type", "proof"))
    answer_type = str(metadata.get("answer_type", "proof"))
    response_mode = "proof_full" if problem_type in {"proof", "derivation"} else "answer_only"
    return ProblemIR(
        raw_problem=case.problem,
        normalized_problem=case.problem,
        problem_type=problem_type,
        answer_type=answer_type,
        response_mode=response_mode,
        subject_candidates=[(str(metadata.get("subject", "general")), 1.0)],
        assumptions=[str(item) for item in metadata.get("assumptions", ())],
        constraints=[str(item) for item in metadata.get("constraints", ())],
        target_phrase=case.problem,
        target_kind=str(metadata.get("target_kind", "prove_statement")),
        difficulty_features=[case.case_type],
        risk_flags=[str(metadata["adversarial_reason"])]
        if metadata.get("adversarial_reason")
        else [],
    )


def _expectation_passes(expectation: str, target_rank: int | None) -> bool:
    if expectation == "include":
        return target_rank is not None
    if expectation == "exclude":
        return target_rank is None
    if expectation == "deprioritize":
        return target_rank is None or target_rank > 1
    return False


def _selection_reasons(composition: Any, target: str) -> tuple[str, ...]:
    for item in (*composition.included, *composition.omitted):
        if item.name == target:
            return tuple(item.reasons)
    return ()


__all__ = [
    "S5_CASE_TYPES",
    "S5_DEFAULT_CASE_PATH",
    "S5_SCHEMA_VERSION",
    "S5_SKILL_NAMES",
    "SelectionBenchmarkReport",
    "SelectionObservation",
    "evaluate_s5_ablation",
    "load_s5_cases",
    "run_s5_benchmark",
    "run_selection_benchmark",
    "s5_case_fingerprint",
]
