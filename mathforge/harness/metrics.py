from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any, ClassVar


RUN_METRICS_SCHEMA_VERSION = "1.1"
_OUTCOMES = frozenset({"primary", "fallback", "error", "timeout"})
_ERROR_CODES = frozenset(
    {
        "",
        "parse",
        "context",
        "budget",
        "tool",
        "proof_incomplete",
        "all_candidates_failed",
        "config",
        "per_case_wall_clock_exceeded",
    }
)


@dataclass(frozen=True)
class RunMetrics:
    """Stable per-run counters that are independent of the bounded judge trace."""

    SCHEMA_VERSION: ClassVar[str] = RUN_METRICS_SCHEMA_VERSION

    schema_version: str = RUN_METRICS_SCHEMA_VERSION
    session_id: str = ""
    request_fingerprint: str = ""
    model_calls: int = 0
    estimated_tokens: int = 0
    prompt_tokens: int = 0
    official_prompt_tokens: int = 0
    fallback_prompt_tokens: int = 0
    requested_output_tokens: int = 0
    observed_output_tokens: int = 0
    output_chars: int = 0
    model_call_timeout_count: int = 0
    per_case_wall_clock_timeout_count: int = 0
    final_response_tokens: int = 0
    context_window_tokens: int = 0
    safety_margin_tokens: int = 0
    model_call_elapsed_seconds: float = 0.0
    token_limit_mode: str = ""
    final_response_counting_mode: str = ""
    deadline_phase: str = ""
    claims: int = 0
    tool_calls: int = 0
    isolated_tool_calls: int = 0
    tool_seconds: float = 0.0
    evidence_records: int = 0
    prompt_chars: int = 0
    elapsed_seconds: float = 0.0
    outcome: str = "error"
    final_phase: str = ""
    error_code: str = ""
    fallback_used: bool = False
    context_view_attempts: int = 0
    context_view_failures: int = 0
    tool_checks: int = 0
    tool_timeouts: int = 0
    tool_unknowns: int = 0
    tool_errors: int = 0
    lemma_checks: int = 0
    lemma_errors: int = 0
    repair_attempts: int = 0
    repair_successes: int = 0
    rag_queries: int = 0
    rag_hits: int = 0

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if self.schema_version != self.SCHEMA_VERSION:
            raise ValueError(
                f"unsupported RunMetrics schema version: {self.schema_version!r}"
            )
        if self.outcome not in _OUTCOMES:
            raise ValueError(f"invalid RunMetrics outcome: {self.outcome!r}")
        if self.error_code not in _ERROR_CODES:
            raise ValueError(f"invalid RunMetrics error code: {self.error_code!r}")
        integer_fields = (
            "model_calls",
            "estimated_tokens",
            "prompt_tokens",
            "official_prompt_tokens",
            "fallback_prompt_tokens",
            "requested_output_tokens",
            "observed_output_tokens",
            "output_chars",
            "model_call_timeout_count",
            "per_case_wall_clock_timeout_count",
            "final_response_tokens",
            "context_window_tokens",
            "safety_margin_tokens",
            "claims",
            "tool_calls",
            "isolated_tool_calls",
            "evidence_records",
            "prompt_chars",
            "context_view_attempts",
            "context_view_failures",
            "tool_checks",
            "tool_timeouts",
            "tool_unknowns",
            "tool_errors",
            "lemma_checks",
            "lemma_errors",
            "repair_attempts",
            "repair_successes",
            "rag_queries",
            "rag_hits",
        )
        for name in integer_fields:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"RunMetrics.{name} must be a nonnegative integer")
        for name in (
            "tool_seconds",
            "elapsed_seconds",
            "model_call_elapsed_seconds",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise ValueError(f"RunMetrics.{name} must be nonnegative")
        for name in (
            "session_id",
            "request_fingerprint",
            "final_phase",
            "error_code",
            "token_limit_mode",
            "final_response_counting_mode",
            "deadline_phase",
        ):
            if not isinstance(getattr(self, name), str):
                raise ValueError(f"RunMetrics.{name} must be a string")
        if not isinstance(self.fallback_used, bool):
            raise ValueError("RunMetrics.fallback_used must be a boolean")
        if self.fallback_used != (self.outcome == "fallback"):
            raise ValueError("RunMetrics fallback flag does not match outcome")
        if (
            self.official_prompt_tokens + self.fallback_prompt_tokens
            != self.prompt_tokens
        ):
            raise ValueError("prompt counting-mode totals do not match prompt tokens")
        if self.model_call_timeout_count > self.model_calls:
            raise ValueError("model timeout count cannot exceed model calls")
        if self.per_case_wall_clock_timeout_count not in {0, 1}:
            raise ValueError("per-case wall-clock timeout count must be zero or one")
        if (self.outcome == "timeout") != (
            self.per_case_wall_clock_timeout_count == 1
        ):
            raise ValueError("per-case wall-clock timeout count does not match outcome")
        if self.context_view_failures > self.context_view_attempts:
            raise ValueError("context failures cannot exceed attempts")
        if self.tool_timeouts + self.tool_unknowns + self.tool_errors > self.tool_checks:
            raise ValueError("tool outcome counters cannot exceed checks")
        if self.lemma_errors > self.lemma_checks:
            raise ValueError("lemma errors cannot exceed checks")
        if self.repair_successes > self.repair_attempts:
            raise ValueError("repair successes cannot exceed attempts")
        if self.rag_hits > self.rag_queries:
            raise ValueError("RAG hits cannot exceed queries")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RunMetrics:
        if not isinstance(payload, dict):
            raise ValueError("RunMetrics payload must be an object")
        allowed = {item.name for item in fields(cls)}
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"unknown RunMetrics fields: {sorted(unknown)}")
        return cls(**payload)


def collect_run_metrics(
    *,
    budget: Any,
    internal_events: list[dict[str, Any]],
    session_id: str,
    request_fingerprint: str,
    outcome: str,
    final_phase: str,
    error_code: str,
) -> RunMetrics:
    context_successes = _event_count(internal_events, "context_view_built")
    context_failures = _event_count(internal_events, "context_budget_infeasible")
    checks = [
        check
        for event in internal_events
        if event.get("event") == "tool_checks"
        for check in event.get("checks", [])
        if isinstance(check, dict)
    ]
    lemma_checks = sum(
        _nonnegative_int(event.get("checked_count", 0))
        for event in internal_events
        if event.get("event") == "lemma_loop_completed"
    )
    lemma_errors = sum(
        _nonnegative_int(event.get("error_count", 0))
        for event in internal_events
        if event.get("event") == "lemma_loop_completed"
    )
    repair_events = [
        event for event in internal_events if event.get("event") == "repair_completed"
    ]
    retrieval_events = [
        event for event in internal_events if event.get("event") == "retrieval_completed"
    ]
    return RunMetrics(
        session_id=session_id,
        request_fingerprint=request_fingerprint,
        model_calls=budget.used_calls,
        estimated_tokens=budget.used_tokens,
        prompt_tokens=budget.prompt_tokens,
        official_prompt_tokens=budget.official_prompt_tokens,
        fallback_prompt_tokens=budget.fallback_prompt_tokens,
        requested_output_tokens=budget.requested_output_tokens,
        observed_output_tokens=budget.observed_output_tokens,
        output_chars=budget.output_chars,
        model_call_timeout_count=budget.model_call_timeout_count,
        final_response_tokens=budget.final_response_tokens,
        context_window_tokens=budget.model_context_window_tokens,
        safety_margin_tokens=budget.context_safety_margin_tokens,
        model_call_elapsed_seconds=round(
            budget.model_call_elapsed_seconds,
            6,
        ),
        token_limit_mode=budget.token_limit_mode,
        final_response_counting_mode=budget.final_response_counting_mode,
        deadline_phase=budget.deadline.phase(),
        claims=budget.used_claims,
        tool_calls=budget.used_tool_calls,
        isolated_tool_calls=budget.used_isolated_tool_calls,
        tool_seconds=round(budget.used_tool_seconds, 6),
        evidence_records=budget.used_evidence_records,
        prompt_chars=budget.used_prompt_chars,
        elapsed_seconds=round(budget.deadline.elapsed_seconds(), 6),
        outcome=outcome,
        final_phase=final_phase,
        error_code=error_code,
        fallback_used=outcome == "fallback",
        context_view_attempts=context_successes + context_failures,
        context_view_failures=context_failures,
        tool_checks=len(checks),
        tool_timeouts=sum(
            check.get("outcome_reason") == "timeout" for check in checks
        ),
        tool_unknowns=sum(
            check.get("status") == "unknown"
            and check.get("outcome_reason") != "timeout"
            for check in checks
        ),
        tool_errors=sum(
            check.get("status") == "error"
            or check.get("outcome_reason") == "error"
            for check in checks
        ),
        lemma_checks=lemma_checks,
        lemma_errors=lemma_errors,
        repair_attempts=len(repair_events),
        repair_successes=sum(
            not bool(event.get("rolled_back", True)) for event in repair_events
        ),
        rag_queries=len(retrieval_events),
        rag_hits=sum(
            bool(event.get("card_ids", []))
            for event in retrieval_events
            if isinstance(event.get("card_ids", []), list)
        ),
    )


def _event_count(events: list[dict[str, Any]], name: str) -> int:
    return sum(event.get("event") == name for event in events)


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
