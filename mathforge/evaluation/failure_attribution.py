"""Deterministic, one-primary-cause attribution for benchmark failures.

The attribution layer consumes public result/metrics/trace data only.  It is
not an LLM role and it never attempts to infer private reasoning.  A case can
have several contributing signals, but the stable precedence below assigns at
most one primary cause so aggregate failure counts remain auditable.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


PRIMARY_FAILURE_CAUSES = (
    "PARSER_ERROR",
    "ROUTER_ERROR",
    "SKILL_SELECTION_ERROR",
    "METHOD_SELECTION_ERROR",
    "REASONING_ERROR",
    "STATE_LOSS",
    "TRUNCATION",
    "CANDIDATE_REBUILD_ERROR",
    "TOOL_FALSE_SIGNAL",
    "VERIFIER_FALSE_ACCEPT",
    "VERIFIER_FALSE_REJECT",
    "REPAIR_REGRESSION",
    "ARBITRATION_ERROR",
    "FORMATTER_ERROR",
    "TRACE_CONTRACT_ERROR",
    "TIMEOUT",
    "PROVIDER_ERROR",
    "PROTOCOL_ERROR",
)
FAILURE_CAUSES = PRIMARY_FAILURE_CAUSES
_CAUSE_SET = frozenset(PRIMARY_FAILURE_CAUSES)

# Upstream execution failures win over downstream symptoms.  REASONING_ERROR
# is retained as the final, explicit fallback for an otherwise unexplained
# incorrect answer.
_PRECEDENCE = (
    "PARSER_ERROR",
    "ROUTER_ERROR",
    "SKILL_SELECTION_ERROR",
    "METHOD_SELECTION_ERROR",
    "STATE_LOSS",
    "TRUNCATION",
    "CANDIDATE_REBUILD_ERROR",
    "TOOL_FALSE_SIGNAL",
    "VERIFIER_FALSE_ACCEPT",
    "VERIFIER_FALSE_REJECT",
    "REPAIR_REGRESSION",
    "ARBITRATION_ERROR",
    "FORMATTER_ERROR",
    "TRACE_CONTRACT_ERROR",
    "TIMEOUT",
    "PROVIDER_ERROR",
    "PROTOCOL_ERROR",
    "REASONING_ERROR",
)


@dataclass(frozen=True)
class FailureAttribution:
    """Public attribution for one case.

    ``primary_cause`` is ``None`` for a successful or unscored case.  Failed
    and incorrect cases always receive exactly one value from
    :data:`PRIMARY_FAILURE_CAUSES`.
    """

    primary_cause: str | None
    secondary_causes: tuple[str, ...] = ()
    case_id: str = ""

    def __post_init__(self) -> None:
        if self.primary_cause is not None and self.primary_cause not in _CAUSE_SET:
            raise ValueError(f"unknown primary failure cause: {self.primary_cause}")
        if len(set(self.secondary_causes)) != len(self.secondary_causes):
            raise ValueError("secondary failure causes must be unique")
        if any(cause not in _CAUSE_SET for cause in self.secondary_causes):
            raise ValueError("unknown secondary failure cause")
        if self.primary_cause in self.secondary_causes:
            raise ValueError("primary cause cannot also be secondary")

    @property
    def primary(self) -> str | None:
        return self.primary_cause

    @property
    def secondary(self) -> tuple[str, ...]:
        return self.secondary_causes

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary_cause": self.primary_cause,
            "secondary_causes": list(self.secondary_causes),
        }


def attribute_failure(
    record: Any = None,
    *,
    result: Mapping[str, Any] | None = None,
    metrics: Any = None,
    score: Any = None,
    trace: Iterable[Mapping[str, Any]] | None = None,
    case_id: str = "",
) -> FailureAttribution:
    """Attribute one benchmark record using deterministic public signals.

    The function accepts either a ``BenchmarkRecord``-like object or a plain
    mapping.  Explicit ``result``, ``metrics``, ``score`` and ``trace``
    arguments are useful for small unit fixtures and override values found on
    ``record``.
    """

    source = _record_mapping(record)
    if result is None:
        result = _as_mapping(_value(record, source, "result"))
    if metrics is None:
        metrics = _value(record, source, "run_metrics")
        if metrics is None and result is not None:
            metrics = result.get("run_metrics")
    if score is None:
        score = _value(record, source, "score")
    if trace is None:
        trace_value = result.get("trace", ()) if result is not None else ()
        trace = trace_value if isinstance(trace_value, (list, tuple)) else ()
    if not case_id:
        case_id = str(_value(record, source, "case_id") or _value(
            _as_mapping(_value(record, source, "case")),
            _as_mapping(_value(record, source, "case")),
            "idx",
        ) or "")

    failed = _is_failed_or_incorrect(record, source, result, metrics, score)
    if not failed:
        return FailureAttribution(None, (), case_id)

    text = _signal_text(record, source, result, metrics, score, trace)
    detected = {
        cause for cause, needles in _SIGNALS.items()
        if any(needle in text for needle in needles)
    }
    if not detected:
        detected.add("REASONING_ERROR")
    primary = next(cause for cause in _PRECEDENCE if cause in detected)
    secondary = tuple(
        cause for cause in _PRECEDENCE if cause in detected and cause != primary
    )
    return FailureAttribution(primary, secondary, case_id)


def attribute_case_failure(record: Any) -> FailureAttribution:
    """Alias named after the benchmark case abstraction."""

    return attribute_failure(record)


def classify_failure(record: Any) -> FailureAttribution:
    """Backward-friendly alias for callers that use ``classify`` terminology."""

    return attribute_failure(record)


def aggregate_failure_attribution(
    attributions: Iterable[FailureAttribution | Mapping[str, Any]],
    *,
    case_count: int | None = None,
) -> dict[str, Any]:
    """Aggregate primary/secondary causes while preserving count invariants."""

    normalized = [_normalize_attribution(item) for item in attributions]
    total_cases = len(normalized) if case_count is None else int(case_count)
    if total_cases < len(normalized):
        raise ValueError("case_count cannot be smaller than attribution count")
    primary_counts = Counter(
        item.primary_cause for item in normalized if item.primary_cause is not None
    )
    secondary_counts = Counter(
        cause
        for item in normalized
        for cause in item.secondary_causes
    )
    attributed = sum(primary_counts.values())
    return {
        "case_count": total_cases,
        "failed_or_incorrect_count": attributed,
        "attributed_count": attributed,
        # ``None`` is the valid representation for successful/unscored cases;
        # only cases omitted from the supplied collection are unattributed.
        "unattributed_count": max(0, total_cases - len(normalized)),
        "primary_total": attributed,
        "secondary_total": sum(secondary_counts.values()),
        "primary_counts": {
            cause: primary_counts[cause]
            for cause in PRIMARY_FAILURE_CAUSES
            if primary_counts[cause]
        },
        "secondary_counts": {
            cause: secondary_counts[cause]
            for cause in PRIMARY_FAILURE_CAUSES
            if secondary_counts[cause]
        },
    }


def validate_failure_attributions(
    attributions: Iterable[FailureAttribution | Mapping[str, Any]],
    *,
    expected_failed_count: int | None = None,
) -> list[str]:
    """Check the one-primary-cause invariant for an attribution collection."""

    normalized: list[FailureAttribution] = []
    errors: list[str] = []
    for index, item in enumerate(attributions):
        try:
            normalized.append(_normalize_attribution(item))
        except (TypeError, ValueError) as error:
            errors.append(f"attribution {index} is invalid: {error}")
    if expected_failed_count is not None:
        actual = sum(item.primary_cause is not None for item in normalized)
        if actual != expected_failed_count:
            errors.append(
                "primary attribution total does not match failed/incorrect cases: "
                f"{actual} != {expected_failed_count}"
            )
    return errors


_SIGNALS: dict[str, tuple[str, ...]] = {
    "PARSER_ERROR": (
        "parser_error", "parse_error", "problem_parse_failed", "parse_failed",
        "parse failure", "error_code=parse",
    ),
    "ROUTER_ERROR": (
        "router_error", "route_error", "router_failed", "route_failed",
        "routing_error", "routing_failed",
    ),
    "SKILL_SELECTION_ERROR": (
        "skill_selection_error", "skill_error", "skill_select_failed",
        "selected_skill_error",
    ),
    "METHOD_SELECTION_ERROR": (
        "method_selection_error", "method_error", "method_select_failed",
        "strategy_selection_error",
    ),
    "STATE_LOSS": (
        "state_loss", "state_lost", "context_lost", "checkpoint_lost",
        "session_state_missing",
    ),
    "TRUNCATION": (
        "truncation", "truncated", "finish_reason_length", "incomplete_response",
        "candidate_json_incomplete", "response_cut_off", "cutoff",
    ),
    "CANDIDATE_REBUILD_ERROR": (
        "candidate_rebuild_error", "candidate_rebuild_failed", "rebuild_error",
        "candidate_recovery_error",
    ),
    "TOOL_FALSE_SIGNAL": (
        "tool_false_signal", "tool_false_positive", "tool_contradiction",
        "false_tool_evidence",
    ),
    "VERIFIER_FALSE_ACCEPT": (
        "verifier_false_accept", "false_accept", "verification_false_accept",
    ),
    "VERIFIER_FALSE_REJECT": (
        "verifier_false_reject", "false_reject", "verification_false_reject",
    ),
    "REPAIR_REGRESSION": (
        "repair_regression", "repair_rollback", "post_repair_regression",
    ),
    "ARBITRATION_ERROR": (
        "arbitration_error", "wrong_arbitration", "arbitration_wrong",
        "selected_wrong_candidate",
    ),
    "FORMATTER_ERROR": (
        "formatter_error", "formatting_error", "output_format_error",
        "format_error",
    ),
    "TRACE_CONTRACT_ERROR": (
        "trace_contract_error", "trace_invalid", "trace_validation_error",
        "official_trace_invalid",
    ),
    "TIMEOUT": (
        "timeout", "deadline_exceeded", "wall_clock_exceeded", "deadline_timeout",
    ),
    "PROVIDER_ERROR": (
        "provider_error", "provider_failure", "transport_error", "transport_failure",
        "model_call_failure", "http_error", "network_error", "api_error",
        "provider_5xx", "rate_limited",
    ),
    "PROTOCOL_ERROR": (
        "protocol_error", "protocol_invalid", "schema_invalid", "schema_error",
        "response_shape_invalid", "agent_turn_invalid", "invalid_response",
    ),
    "REASONING_ERROR": (
        "reasoning_error", "wrong_answer", "answer_wrong", "incorrect",
        "mismatch", "solver_wrong", "candidate_wrong", "not_correct",
    ),
}


def _record_mapping(record: Any) -> Mapping[str, Any]:
    return record if isinstance(record, Mapping) else {}


def _value(record: Any, mapping: Mapping[str, Any], name: str) -> Any:
    if isinstance(mapping, Mapping) and name in mapping:
        return mapping[name]
    return getattr(record, name, None) if record is not None else None


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _is_failed_or_incorrect(
    record: Any,
    mapping: Mapping[str, Any],
    result: Mapping[str, Any] | None,
    metrics: Any,
    score: Any,
) -> bool:
    score_scored = _field(score, "scored")
    score_correct = _field(score, "correct")
    score_reason = str(_field(score, "reason") or "")
    if score_scored is True:
        return score_correct is not True
    if score_reason.startswith("invalid_expected"):
        return False
    outcome = str(
        _field(metrics, "outcome")
        or (result or {}).get("status", "")
        or _value(record, mapping, "status")
        or ""
    ).casefold()
    if outcome in {"timeout", "error", "failed", "failure", "fallback"}:
        return True
    if _field(metrics, "error_code") or (result or {}).get("error_type"):
        return True
    if _value(record, mapping, "json_valid") is False:
        return True
    # A direct fixture with an explicit failure signal is treated as failed
    # even when it has no RunMetrics/Score object.
    text = _signal_text(record, mapping, result, metrics, score, ())
    return any(
        needle in text
        for needles in _SIGNALS.values()
        for needle in needles
        if needle not in _SIGNALS["REASONING_ERROR"]
    )


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None) if value is not None else None


def _signal_text(
    record: Any,
    mapping: Mapping[str, Any],
    result: Mapping[str, Any] | None,
    metrics: Any,
    score: Any,
    trace: Iterable[Mapping[str, Any]],
) -> str:
    values: list[str] = []
    for item in (mapping, result or {}, metrics, score):
        _collect_text(item, values)
    for event in trace:
        _collect_text(event, values)
    if record is not None and not isinstance(record, Mapping):
        _collect_text(getattr(record, "__dict__", {}), values)
    return " ".join(values).casefold()


def _collect_text(value: Any, output: list[str]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            output.append(str(key))
            if isinstance(item, (str, int, float, bool)):
                output.append(str(item))
            elif isinstance(item, Mapping):
                _collect_text(item, output)
            elif isinstance(item, (list, tuple, set)):
                for nested in item:
                    _collect_text(nested, output)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            _collect_text(item, output)
    elif hasattr(value, "__dict__"):
        _collect_text(vars(value), output)
    elif isinstance(value, (str, int, float, bool)):
        output.append(str(value))


def _normalize_attribution(
    value: FailureAttribution | Mapping[str, Any],
) -> FailureAttribution:
    if isinstance(value, FailureAttribution):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("attribution must be a FailureAttribution or object")
    primary = value.get("primary_cause", value.get("primary"))
    secondary = value.get("secondary_causes", value.get("secondary", ()))
    if secondary is None:
        secondary = ()
    if isinstance(secondary, str):
        secondary = (secondary,)
    return FailureAttribution(
        primary if primary is None else str(primary),
        tuple(str(item) for item in secondary),
        str(value.get("case_id", "")),
    )
