"""E8 benchmark, ablation and release-freeze contracts.

E8 is deliberately an evaluation layer.  It consumes already serialised
``BenchmarkRecord`` objects and never changes the model or public-result
contract.  The module provides deterministic suite validation, paired-arm
checks, the complete metric vocabulary from the E8 plan, and a fail-closed
freeze gate that can be used by release tooling.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from mathforge.benchmark import (
    BenchmarkCase,
    BenchmarkRecord,
    load_jsonl,
    paired_significance,
    summarize,
)


E8_SCHEMA_VERSION = "1.0"

SUITE_IDS = ("B1", "B2", "B3")
WORKFLOW_ARMS = tuple(f"W{index}" for index in range(9))
SKILL_ARMS = tuple(f"S{index}" for index in range(4))
VERIFICATION_ARMS = tuple(f"V{index}" for index in range(4))
PROMPT_ARMS = ("P0", "P1")
REQUIRED_REPETITIONS = 3

E8_METRIC_NAMES = (
    "overall_accuracy",
    "accuracy_by_domain",
    "accuracy_by_problem_type",
    "accuracy_by_risk",
    "valid_output_rate",
    "candidate_availability",
    "zero_candidate_rate",
    "timeout_rate",
    "truncation_rate",
    "truncation_by_stage",
    "recovered_answer_accuracy",
    "router_accept_rate",
    "router_confusion_matrix",
    "skill_selection_precision",
    "skill_selection_recall",
    "skill_accuracy_delta",
    "independent_candidate_rate",
    "peer_review_closure_rate",
    "verifier_false_accept",
    "verifier_false_reject",
    "repair_success_rate",
    "repair_regression_rate",
    "audit_closure_rate",
    "closure_completion_rate",
    "mean_logical_calls",
    "transport_attempts",
    "p50_latency",
    "p95_latency",
)


@dataclass(frozen=True)
class BenchmarkSuiteSpec:
    suite_id: str
    name: str
    purpose: str
    minimum_cases: int
    maximum_cases: int | None
    required_problem_types: tuple[str, ...] = ()
    required_challenge_tags: tuple[str, ...] = ()

    def validate(self, cases: Sequence[BenchmarkCase]) -> tuple[str, ...]:
        errors: list[str] = []
        if len(cases) < self.minimum_cases:
            errors.append(
                f"{self.suite_id} requires at least {self.minimum_cases} cases"
            )
        if self.maximum_cases is not None and len(cases) > self.maximum_cases:
            errors.append(
                f"{self.suite_id} allows at most {self.maximum_cases} cases"
            )
        if not cases:
            errors.append(f"{self.suite_id} is empty")
            return tuple(errors)
        if any(case.expected_answer is None for case in cases):
            errors.append(f"{self.suite_id} contains a case without expected_answer")
        observed_types = {case.problem_type for case in cases}
        for required in self.required_problem_types:
            if required not in observed_types:
                errors.append(f"{self.suite_id} is missing problem_type {required}")
        observed_tags = {
            tag
            for case in cases
            for tag in _case_challenge_tags(case)
        }
        for required in self.required_challenge_tags:
            if required not in observed_tags:
                errors.append(f"{self.suite_id} is missing challenge tag {required}")
        return tuple(errors)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BenchmarkSuiteValidation:
    suite_id: str
    case_count: int
    errors: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite_id": self.suite_id,
            "case_count": self.case_count,
            "valid": self.valid,
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class AblationArmSpec:
    arm_id: str
    family: str
    description: str
    config_path: str | None = None
    minimum_repetitions: int = REQUIRED_REPETITIONS

    def __post_init__(self) -> None:
        if not self.arm_id or not self.family:
            raise ValueError("ablation arm requires arm_id and family")
        if self.minimum_repetitions < 1:
            raise ValueError("minimum_repetitions must be positive")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AblationValidation:
    family: str
    arm_ids: tuple[str, ...]
    common_case_ids: tuple[str, ...]
    repetitions_by_arm: dict[str, int]
    provider_health_states: dict[str, dict[str, int]]
    interleaved: bool
    errors: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "arm_ids": list(self.arm_ids),
            "common_case_ids": list(self.common_case_ids),
            "repetitions_by_arm": dict(self.repetitions_by_arm),
            "provider_health_states": {
                key: dict(value)
                for key, value in self.provider_health_states.items()
            },
            "interleaved": self.interleaved,
            "valid": self.valid,
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class FreezeGateResult:
    eligible: bool
    blockers: tuple[str, ...]
    checks: dict[str, bool]
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": E8_SCHEMA_VERSION,
            "eligible": self.eligible,
            "blockers": list(self.blockers),
            "checks": dict(self.checks),
            "metrics": dict(self.metrics),
        }


BENCHMARK_SUITES: dict[str, BenchmarkSuiteSpec] = {
    "B1": BenchmarkSuiteSpec(
        "B1",
        "Gradeability / Protocol Canary",
        "Fast schema, truncation and public-output checks.",
        8,
        20,
        required_problem_types=("protocol_canary",),
    ),
    "B2": BenchmarkSuiteSpec(
        "B2",
        "Core Math Set",
        "Representative calculation, proof, derivation and answer-format cases.",
        6,
        None,
        required_problem_types=(
            "calculation",
            "proof",
            "derivation",
            "multiple_choice",
            "fill_blank",
            "mixed",
        ),
    ),
    "B3": BenchmarkSuiteSpec(
        "B3",
        "Failure Challenge Set",
        "Adversarial cases for recovery, verification, repair and final audit.",
        8,
        None,
        required_challenge_tags=(
            "truncation",
            "ambiguity",
            "wrong_lemma",
            "counterexample",
            "repair",
            "rollback",
            "final_audit",
            "long_horizon",
            "domain_tool_boundary",
        ),
    ),
}


def _arm_specs() -> tuple[AblationArmSpec, ...]:
    workflow_descriptions = (
        "current baseline",
        "stateful truncation",
        "recovered corroboration",
        "executable Skill",
        "authoritative TaskGraph",
        "verified fact/proof backbone",
        "risk-aware completion",
        "parallel progress",
        "semantic proof renderer",
    )
    specs = [
        AblationArmSpec(
            arm_id=f"W{index}",
            family="workflow",
            description=description,
            config_path=f"config/ablation/W{index}.json",
        )
        for index, description in enumerate(workflow_descriptions)
    ]
    specs.extend(
        AblationArmSpec(
            arm_id=f"S{index}",
            family="skill",
            description=description,
            config_path=f"config/ablation/S{index}.json",
        )
        for index, description in enumerate(
            (
                "Skill off",
                "V3 passive prompt",
                "V3 + capability admission",
                "V3 executable hooks/fallback",
            )
        )
    )
    specs.extend(
        AblationArmSpec(
            arm_id=f"V{index}",
            family="verification",
            description=description,
            config_path=f"config/ablation/V{index}.json",
        )
        for index, description in enumerate(
            ("candidate only", "+ verifier", "+ repair", "+ final audit")
        )
    )
    specs.extend(
        AblationArmSpec(
            arm_id=arm_id,
            family="prompt",
            description=description,
            config_path=f"config/ablation/{arm_id}.json",
        )
        for arm_id, description in (
            ("P0", "AgentTurn 1.0"),
            ("P1", "Lite semantic payload"),
        )
    )
    return tuple(specs)


ABLATION_ARMS = _arm_specs()


def ablation_arm_specs(family: str | None = None) -> tuple[AblationArmSpec, ...]:
    """Return the immutable E8 arm registry, optionally filtered by family."""

    if family is None:
        return ABLATION_ARMS
    return tuple(item for item in ABLATION_ARMS if item.family == family)


def validate_benchmark_suite(
    suite_id: str,
    cases: Iterable[BenchmarkCase],
) -> BenchmarkSuiteValidation:
    """Validate a named B1/B2/B3 suite without mutating its cases."""

    spec = BENCHMARK_SUITES.get(str(suite_id))
    normalized = tuple(cases)
    if spec is None:
        return BenchmarkSuiteValidation(
            str(suite_id),
            len(normalized),
            (f"unknown benchmark suite: {suite_id}",),
        )
    return BenchmarkSuiteValidation(
        spec.suite_id,
        len(normalized),
        spec.validate(normalized),
    )


def load_benchmark_suite(path: Path, suite_id: str) -> tuple[BenchmarkCase, ...]:
    """Load and fail closed on a named suite from JSONL or a JSON array."""

    cases = tuple(load_jsonl(path))
    validation = validate_benchmark_suite(suite_id, cases)
    if not validation.valid:
        raise ValueError("; ".join(validation.errors))
    return cases


def validate_paired_ablation(
    family: str,
    runs_by_arm: Mapping[str, Iterable[Any]],
    *,
    minimum_repetitions: int = REQUIRED_REPETITIONS,
    execution_order: Sequence[str] | None = None,
) -> AblationValidation:
    """Check same-case, repeated, interleaved and provider-health evidence.

    A run row may be a ``BenchmarkRecord`` or a serialised mapping containing
    ``case_id``/``case`` and ``repetition_index``/``repetition``.  Provider
    health must be observable in ``run_metrics.provider_health_state`` or the
    row is rejected; this prevents a provider outage being silently assigned
    to one treatment arm.
    """

    arm_specs = {item.arm_id: item for item in ablation_arm_specs(family)}
    arm_ids = tuple(str(item) for item in runs_by_arm)
    errors: list[str] = []
    for arm_id in arm_ids:
        if arm_id not in arm_specs:
            errors.append(f"unknown {family} ablation arm: {arm_id}")
    if not arm_ids:
        errors.append("at least two ablation arms are required")
    if len(arm_ids) < 2:
        errors.append("paired ablation requires at least two arms")

    by_arm: dict[str, dict[tuple[str, int], Any]] = {}
    repetitions_by_arm: dict[str, int] = {}
    health_by_arm: dict[str, dict[str, int]] = {}
    for arm_id, rows in runs_by_arm.items():
        seen: dict[tuple[str, int], Any] = {}
        health_counts: Counter[str] = Counter()
        for row in rows:
            case_id = _row_case_id(row)
            repetition = _row_repetition(row)
            if not case_id:
                errors.append(f"{arm_id} has a run without case_id")
                continue
            key = (case_id, repetition)
            if key in seen:
                errors.append(f"{arm_id} duplicates case/repetition {key}")
            seen[key] = row
            health = _row_provider_health(row)
            if not health:
                errors.append(f"{arm_id} lacks provider health for {key}")
            else:
                health_counts[health] += 1
        by_arm[arm_id] = seen
        repetitions_by_arm[arm_id] = len({rep for _, rep in seen})
        health_by_arm[arm_id] = dict(sorted(health_counts.items()))
        required = max(
            minimum_repetitions,
            arm_specs.get(
                arm_id,
                AblationArmSpec(arm_id, family, "unregistered"),
            ).minimum_repetitions,
        )
        if repetitions_by_arm[arm_id] < required:
            errors.append(
                f"{arm_id} has {repetitions_by_arm[arm_id]} repetitions; "
                f"requires {required}"
            )

    common_case_ids: set[str] = set()
    if by_arm:
        case_sets = [set(case_id for case_id, _ in rows) for rows in by_arm.values()]
        common_case_ids = set.intersection(*case_sets) if case_sets else set()
        union_case_ids = set.union(*case_sets) if case_sets else set()
        if any(case_set != union_case_ids for case_set in case_sets):
            errors.append("paired arms do not use the same case IDs")
        for case_id in sorted(common_case_ids):
            reps = [
                {rep for candidate_id, rep in rows if candidate_id == case_id}
                for rows in by_arm.values()
            ]
            if any(rep_set != reps[0] for rep_set in reps[1:]):
                errors.append(f"paired arms have mismatched repetitions for {case_id}")

    order = tuple(str(item) for item in (execution_order or ()))
    interleaved = _is_interleaved(order, arm_ids)
    if execution_order is not None and not interleaved:
        errors.append("ablation execution order is grouped instead of interleaved")
    return AblationValidation(
        family=str(family),
        arm_ids=arm_ids,
        common_case_ids=tuple(sorted(common_case_ids)),
        repetitions_by_arm=repetitions_by_arm,
        provider_health_states=health_by_arm,
        interleaved=interleaved,
        errors=tuple(dict.fromkeys(errors)),
    )


def summarize_ablation_arms(
    family: str,
    records_by_arm: Mapping[str, Sequence[BenchmarkRecord]],
    *,
    execution_order: Sequence[str] | None = None,
    minimum_repetitions: int = REQUIRED_REPETITIONS,
) -> dict[str, Any]:
    """Produce paired arm summaries and exact paired comparisons."""

    validation = validate_paired_ablation(
        family,
        records_by_arm,
        minimum_repetitions=minimum_repetitions,
        execution_order=execution_order,
    )
    summaries = {
        arm_id: summarize(list(records)) for arm_id, records in records_by_arm.items()
    }
    pairwise: dict[str, dict[str, Any]] = {}
    arm_ids = tuple(records_by_arm)
    for index, left in enumerate(arm_ids):
        for right in arm_ids[index + 1 :]:
            pairwise[f"{left}_vs_{right}"] = paired_significance(
                list(records_by_arm[left]),
                list(records_by_arm[right]),
            )
    return {
        "schema_version": E8_SCHEMA_VERSION,
        "family": family,
        "validation": validation.to_dict(),
        "arms": summaries,
        "pairwise": pairwise,
        "claim_policy": {
            "minimum_repetitions": minimum_repetitions,
            "requires_interleaved_order": True,
            "requires_provider_health": True,
            "accuracy_claim_requires_non_regression": True,
        },
    }


def summarize_e8(
    records: Iterable[BenchmarkRecord],
    *,
    provider_health: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Compute the full E8 metric vocabulary from per-case records.

    Metrics that require gold labels not present in a run are returned as
    explicit zero/empty values together with their denominator.  They are not
    guessed from model text or private reasoning.
    """

    rows = list(records)
    base = summarize(rows)
    total = len(rows)
    scored = [record for record in rows if record.score.scored]
    correct = [record for record in scored if record.score.correct is True]
    valid = [record for record in rows if _valid_result(record)]
    candidate_rows = [record for record in rows if _candidate_ids(record)]
    timeout_rows = [record for record in rows if record.run_metrics.outcome == "timeout"]
    truncation_rows = [record for record in rows if _truncation_events(record)]
    recovered_rows = [record for record in rows if _has_recovery(record)]
    recovered_scored = [record for record in recovered_rows if record.score.scored]
    recovered_correct = [
        record for record in recovered_scored if record.score.correct is True
    ]

    risk_groups = _group_accuracy(rows, _risk_level)
    domain_groups = _group_accuracy(rows, lambda item: item.case.subject)
    problem_groups = _group_accuracy(rows, lambda item: item.case.problem_type)
    truncation_by_stage: Counter[str] = Counter()
    for record in truncation_rows:
        for event in _trace(record):
            if event.get("event") in {
                "truncation_assessed",
                "candidate_partial_recovery_started",
            }:
                stage = str(event.get("stage") or event.get("role") or "unknown")
                truncation_by_stage[stage] += 1

    router_accepts = sum(_router_accepted(record) for record in rows)
    independent = sum(_independent_candidates(record) for record in rows)
    peer_closed = sum(_peer_review_closed(record) for record in rows)
    audit_closed = sum(_audit_closed(record) for record in rows)
    closure_complete = sum(_closure_complete(record) for record in rows)
    repair_attempts = sum(record.run_metrics.repair_attempts for record in rows)
    repair_successes = sum(record.run_metrics.repair_successes for record in rows)
    repair_regressions = sum(_repair_regression_count(record) for record in rows)
    false_accept = sum(_verifier_false_accept(record) for record in scored)
    false_reject = sum(_verifier_false_reject(record) for record in scored)
    skill_precision, skill_recall, skill_delta = _skill_metrics(rows)
    route_matrix = _router_confusion_matrix(rows)
    latencies = sorted(record.latency_seconds for record in rows)
    result = {
        "schema_version": E8_SCHEMA_VERSION,
        "overall_accuracy": base.get("accuracy"),
        "accuracy_by_domain": domain_groups,
        "accuracy_by_problem_type": problem_groups,
        "accuracy_by_risk": risk_groups,
        "valid_output_rate": _rate(len(valid), total),
        "candidate_availability": _rate(len(candidate_rows), total),
        "zero_candidate_rate": _rate(total - len(candidate_rows), total),
        "timeout_rate": _rate(len(timeout_rows), total),
        "truncation_rate": _rate(len(truncation_rows), total),
        "truncation_by_stage": dict(sorted(truncation_by_stage.items())),
        "recovered_answer_accuracy": _rate(len(recovered_correct), len(recovered_scored)),
        "router_accept_rate": _rate(router_accepts, total),
        "router_confusion_matrix": route_matrix,
        "skill_selection_precision": skill_precision,
        "skill_selection_recall": skill_recall,
        "skill_accuracy_delta": skill_delta,
        "independent_candidate_rate": _rate(independent, total),
        "peer_review_closure_rate": _rate(peer_closed, total),
        "verifier_false_accept": false_accept,
        "verifier_false_reject": false_reject,
        "repair_success_rate": _rate(repair_successes, repair_attempts),
        "repair_regression_rate": _rate(repair_regressions, repair_attempts),
        "audit_closure_rate": _rate(audit_closed, total),
        "closure_completion_rate": _rate(closure_complete, total),
        "mean_logical_calls": _mean(
            [record.run_metrics.model_calls for record in rows]
        ),
        "transport_attempts": sum(
            record.run_metrics.transport_attempts for record in rows
        ),
        "p50_latency": _percentile(latencies, 0.50),
        "p95_latency": _percentile(latencies, 0.95),
        "case_count": total,
        "scored_count": len(scored),
        "recovered_case_count": len(recovered_rows),
        "provider_health": dict(provider_health or _provider_health(rows)),
        "metric_denominators": {
            "accuracy": len(scored),
            "valid_output": total,
            "candidate_availability": total,
            "recovered_answer_accuracy": len(recovered_scored),
            "repair": repair_attempts,
        },
        "base_summary": base,
    }
    for name in E8_METRIC_NAMES:
        result.setdefault(name, None)
    return result


def evaluate_freeze_gate(
    *,
    engineering: Mapping[str, bool],
    architecture: Mapping[str, Any],
    summary: Mapping[str, Any],
    ablation_validation: Mapping[str, Any] | None = None,
    baseline_accuracy: float | None = None,
    human_review: bool = False,
    required_repetitions: int = REQUIRED_REPETITIONS,
) -> FreezeGateResult:
    """Evaluate E8-T08 without changing any release/configuration files."""

    checks: dict[str, bool] = {}
    blockers: list[str] = []
    for name, value in engineering.items():
        checks[f"engineering.{name}"] = type(value) is bool and value
        if not checks[f"engineering.{name}"]:
            blockers.append(f"engineering gate failed: {name}")

    architecture_rules = {
        "model_call_graph_mapping_rate": lambda value: _number(value) == 1.0,
        "stale_result_publish_count": lambda value: _number(value) == 0.0,
        "plan_version_mismatch_count": lambda value: _number(value) == 0.0,
        "session_cross_contamination_count": lambda value: _number(value) == 0.0,
    }
    for name, predicate in architecture_rules.items():
        passed = name in architecture and predicate(architecture[name])
        checks[f"architecture.{name}"] = passed
        if not passed:
            blockers.append(f"architecture gate failed: {name}")

    availability_rules = {
        "zero_candidate_rate": (0.05, "at_most"),
        "fallback_rate": (0.05, "at_most"),
        "format_caused_success_wrong": (0.0, "equal"),
    }
    for name, (threshold, mode) in availability_rules.items():
        value = summary.get(name)
        passed = _number(value) <= threshold if mode == "at_most" else _number(value) == threshold
        checks[f"availability.{name}"] = passed
        if not passed:
            blockers.append(f"availability gate failed: {name}")

    accuracy = summary.get("overall_accuracy")
    accuracy_passed = (
        accuracy is not None
        and (baseline_accuracy is None or _number(accuracy) + 1e-12 >= baseline_accuracy)
    )
    checks["accuracy.non_regression"] = accuracy_passed
    if not accuracy_passed:
        blockers.append("accuracy is below the effective baseline")

    ablation_passed = _ablation_validation_passed(
        ablation_validation,
        required_repetitions=required_repetitions,
    )
    checks["ablation.repeated_paired_evidence"] = ablation_passed
    if not ablation_passed:
        blockers.append("repeated paired ablation evidence is incomplete")

    checks["human_review.completed"] = bool(human_review)
    if not human_review:
        blockers.append("human mathematical review is incomplete")
    return FreezeGateResult(
        eligible=not blockers,
        blockers=tuple(dict.fromkeys(blockers)),
        checks=checks,
        metrics={
            "overall_accuracy": accuracy,
            "baseline_accuracy": baseline_accuracy,
            "required_repetitions": required_repetitions,
        },
    )


def _case_challenge_tags(case: BenchmarkCase) -> tuple[str, ...]:
    value = getattr(case, "challenge_tags", None)
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(str(item) for item in value if str(item).strip())
    # JSONL loader keeps the public BenchmarkCase stable.  B3 fixtures encode
    # tags in the problem_type as ``failure:<tag>`` when no richer metadata is
    # available.
    problem_type = str(case.problem_type)
    return tuple(
        item for item in problem_type.replace(",", " ").split()
        if item in {
            "truncation",
            "ambiguity",
            "wrong_lemma",
            "counterexample",
            "repair",
            "rollback",
            "final_audit",
            "long_horizon",
            "domain_tool_boundary",
        }
    )


def _trace(record: BenchmarkRecord) -> list[dict[str, Any]]:
    trace = record.result.get("trace", [])
    return [item for item in trace if isinstance(item, dict)] if isinstance(trace, list) else []


def _event(record: BenchmarkRecord, name: str) -> list[dict[str, Any]]:
    return [item for item in _trace(record) if item.get("event") == name]


def _last_event(record: BenchmarkRecord, name: str) -> dict[str, Any]:
    events = _event(record, name)
    return events[-1] if events else {}


def _risk_level(record: BenchmarkRecord) -> str:
    event = _last_event(record, "route_planned")
    risk = str(event.get("risk_level", "")).strip()
    return risk or "unknown"


def _group_accuracy(
    records: Sequence[BenchmarkRecord],
    key,
) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[BenchmarkRecord]] = {}
    for record in records:
        groups.setdefault(str(key(record)), []).append(record)
    return {
        name: {
            "count": len(items),
            "scored_count": sum(item.score.scored for item in items),
            "accuracy": _rate(
                sum(item.score.scored and item.score.correct is True for item in items),
                sum(item.score.scored for item in items),
            ),
        }
        for name, items in sorted(groups.items())
    }


def _valid_result(record: BenchmarkRecord) -> bool:
    result = record.result
    return bool(
        record.json_valid
        and isinstance(result.get("final_response"), str)
        and result.get("final_response", "").strip()
        and isinstance(result.get("trace"), list)
    )


def _candidate_ids(record: BenchmarkRecord) -> set[str]:
    ids: set[str] = set()
    for event in _event(record, "candidate_fanout_completed"):
        ids.update(str(item) for item in event.get("completed", []) if str(item))
    for event_name in ("candidate_generated", "candidate_selected", "final_answer_selected"):
        for event in _event(record, event_name):
            value = event.get("candidate_id") or event.get("selected_candidate_id")
            if value:
                ids.add(str(value))
    return ids


def _truncation_events(record: BenchmarkRecord) -> list[dict[str, Any]]:
    markers = {
        "truncation_assessed",
        "candidate_partial_recovery_started",
        "truncated_candidate_rebuilt",
        "candidate_salvaged",
        "proof_token_canary_degraded",
    }
    return [
        event
        for event in _trace(record)
        if event.get("event") in markers
        or "truncat" in str(event.get("event", "")).casefold()
    ]


def _has_recovery(record: BenchmarkRecord) -> bool:
    return bool(
        _truncation_events(record)
        and (
            _event(record, "candidate_stateful_rebuilt")
            or _event(record, "truncated_candidate_rebuilt")
            or _event(record, "candidate_salvaged")
            or _event(record, "salvaged_candidate_response")
        )
    )


def _router_accepted(record: BenchmarkRecord) -> bool:
    route = _last_event(record, "route_planned")
    return bool(route and route.get("plan_id") and route.get("router_source"))


def _router_confusion_matrix(records: Sequence[BenchmarkRecord]) -> dict[str, dict[str, int]]:
    matrix: dict[str, Counter[str]] = {}
    for record in records:
        expected = str(record.case.subject)
        observed = str(_last_event(record, "route_planned").get("primary_subject", "unknown"))
        if expected == "unknown":
            continue
        matrix.setdefault(expected, Counter())[observed] += 1
    return {
        expected: dict(sorted(observed.items()))
        for expected, observed in sorted(matrix.items())
    }


def _independent_candidates(record: BenchmarkRecord) -> bool:
    # Candidate count or method diversity alone is not independent model
    # evidence.  Count only an explicit public marker, distinct branches, and
    # distinguishable model identities; otherwise the metric stays zero rather
    # than treating correlated agreement as independence.
    events = [
        event
        for event in _event(record, "candidate_generated")
        if event.get("independent_model_call") is True
    ]
    if len(events) < 2:
        return False
    branch_ids = {
        str(event.get("branch_id", "")).strip()
        for event in events
        if str(event.get("branch_id", "")).strip()
    }
    model_ids = {
        str(event.get("model_identity", "")).strip()
        for event in events
        if str(event.get("model_identity", "")).strip()
    }
    return len(branch_ids) >= 2 and len(model_ids) >= 2


def _peer_review_closed(record: BenchmarkRecord) -> bool:
    events = _event(record, "peer_review_completed")
    return bool(events) and all(str(event.get("status", "")) in {"completed", "passed"} for event in events)


def _audit_closed(record: BenchmarkRecord) -> bool:
    events = _event(record, "final_audit_completed")
    return bool(events) and any(
        bool(event.get("complete"))
        or str(event.get("status", "")).casefold() in {"completed", "passed", "complete"}
        for event in events
    )


def _closure_complete(record: BenchmarkRecord) -> bool:
    events = _event(record, "verification_closure_recomputed")
    if not events:
        return False
    closure = events[-1].get("closures", {})
    if not isinstance(closure, dict) or not closure:
        return False
    return all(
        bool(value.get("complete"))
        or str(value.get("status", "")).casefold() in {"complete", "completed", "hard_verified"}
        for value in closure.values()
        if isinstance(value, dict)
    )


def _verifier_false_accept(record: BenchmarkRecord) -> int:
    if record.score.correct is not False:
        return 0
    verifier_pass = any(
        str(event.get("status", "")).casefold() in {"pass", "passed", "completed"}
        for event in _event(record, "peer_review_completed") + _event(record, "verification_closure_recomputed")
    )
    selected = bool(_event(record, "candidate_selected") or _event(record, "final_answer_selected"))
    return int(verifier_pass and selected)


def _verifier_false_reject(record: BenchmarkRecord) -> int:
    if record.score.correct is not True:
        return 0
    rejected = bool(
        _event(record, "hard_evidence_gate")
        and not _candidate_ids(record)
    ) or bool(
        _event(record, "verification_failed")
        and record.run_metrics.outcome != "primary"
    )
    return int(rejected)


def _repair_regression_count(record: BenchmarkRecord) -> int:
    return sum(
        1
        for event in _event(record, "repair_completed")
        if bool(event.get("rolled_back"))
        or "regression" in str(event.get("reason", "")).casefold()
    )


def _skill_metrics(records: Sequence[BenchmarkRecord]) -> tuple[float, float, float]:
    selected = 0
    true_positive = 0
    expected = 0
    on_correct: list[bool] = []
    off_correct: list[bool] = []
    for record in records:
        route = _last_event(record, "route_planned")
        selected_skills = route.get("selected_skills", [])
        if not isinstance(selected_skills, list):
            selected_skills = []
        expected_skills = getattr(record.case, "expected_skills", ())
        if not isinstance(expected_skills, (list, tuple, set, frozenset)):
            expected_skills = ()
        selected += len(selected_skills)
        expected += len(expected_skills)
        true_positive += len(set(str(item) for item in selected_skills) & set(str(item) for item in expected_skills))
        skill_enabled = route.get("skills_enabled")
        if skill_enabled is True:
            on_correct.append(record.score.correct is True)
        elif skill_enabled is False:
            off_correct.append(record.score.correct is True)
    precision = true_positive / selected if selected else 0.0
    recall = true_positive / expected if expected else 0.0
    delta = (
        sum(on_correct) / len(on_correct) - sum(off_correct) / len(off_correct)
        if on_correct and off_correct
        else 0.0
    )
    return precision, recall, delta


def _provider_health(records: Sequence[BenchmarkRecord]) -> dict[str, int]:
    return dict(
        sorted(
            Counter(str(record.run_metrics.provider_health_state) for record in records).items()
        )
    )


def _row_case_id(row: Any) -> str:
    if isinstance(row, BenchmarkRecord):
        return str(row.case.idx)
    if isinstance(row, Mapping):
        case = row.get("case")
        if isinstance(case, Mapping):
            return str(case.get("idx", case.get("id", ""))).strip()
        return str(row.get("case_id", row.get("idx", row.get("id", "")))).strip()
    return str(getattr(getattr(row, "case", None), "idx", ""))


def _row_repetition(row: Any) -> int:
    if isinstance(row, BenchmarkRecord):
        return int(row.repetition_index)
    if isinstance(row, Mapping):
        return int(row.get("repetition_index", row.get("repetition", 0)))
    return int(getattr(row, "repetition_index", 0))


def _row_provider_health(row: Any) -> str:
    if isinstance(row, BenchmarkRecord):
        return str(row.run_metrics.provider_health_state).strip()
    if isinstance(row, Mapping):
        metrics = row.get("run_metrics")
        if isinstance(metrics, Mapping):
            return str(metrics.get("provider_health_state", "")).strip()
        return str(row.get("provider_health_state", "")).strip()
    metrics = getattr(row, "run_metrics", None)
    return str(getattr(metrics, "provider_health_state", "")).strip()


def _is_interleaved(order: Sequence[str], arms: Sequence[str]) -> bool:
    if not order:
        return False
    known = set(arms)
    filtered = [item for item in order if item in known]
    if len(set(filtered)) < 2:
        return False
    return all(left != right for left, right in zip(filtered, filtered[1:]))


def _ablation_validation_passed(
    validation: Mapping[str, Any] | None,
    *,
    required_repetitions: int,
) -> bool:
    if not isinstance(validation, Mapping):
        return False
    if validation.get("valid") is not True or validation.get("interleaved") is not True:
        return False
    repetitions = validation.get("repetitions_by_arm", {})
    if not isinstance(repetitions, Mapping) or not repetitions:
        return False
    return all(_number(value) >= required_repetitions for value in repetitions.values())


def _rate(numerator: int | float, denominator: int | float) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def _mean(values: Sequence[int | float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    index = min(len(values) - 1, max(0, int(round((len(values) - 1) * fraction))))
    return float(values[index])


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


__all__ = [
    "ABLATION_ARMS",
    "AblationArmSpec",
    "AblationValidation",
    "BENCHMARK_SUITES",
    "BenchmarkSuiteSpec",
    "BenchmarkSuiteValidation",
    "E8_METRIC_NAMES",
    "E8_SCHEMA_VERSION",
    "FreezeGateResult",
    "ablation_arm_specs",
    "evaluate_freeze_gate",
    "load_benchmark_suite",
    "summarize_ablation_arms",
    "summarize_e8",
    "validate_benchmark_suite",
    "validate_paired_ablation",
]
