from __future__ import annotations

from typing import Any, Callable, TypeVar

from mathforge.harness.events import EVENT_STAGES, TRACE_SCHEMA_VERSION
from mathforge.output.loop_health import minimal_closed_loop_health


MINIMAL_FALLBACK_RESPONSE = "0"
_T = TypeVar("_T")


class NoThrowTerminalizer:
    """Contain terminal bookkeeping faults and always produce a safe mapping."""

    def __init__(self) -> None:
        self.failed_steps: list[str] = []

    def safe(
        self,
        step: str,
        operation: Callable[[], _T],
        default: _T,
    ) -> _T:
        try:
            return operation()
        except Exception:
            self.failed_steps.append(str(step))
            return default

    def build_result(
        self,
        *,
        final_response: str,
        trace_factory: Callable[[], list[dict[str, Any]]],
        metrics_factory: Callable[[], dict[str, Any]],
        provenance: dict[str, Any],
        outcome: str = "fallback",
        final_phase: str = "fallback_completed",
        error_code: str = "",
    ) -> dict[str, Any]:
        response = (
            final_response
            if isinstance(final_response, str) and final_response.strip()
            else MINIMAL_FALLBACK_RESPONSE
        )
        empty_trace: list[dict[str, Any]] = []
        empty_metrics: dict[str, Any] = {}
        trace: list[dict[str, Any]] = self.safe(
            "trace_build",
            trace_factory,
            empty_trace,
        )
        metrics: dict[str, Any] = self.safe(
            "metrics_build",
            metrics_factory,
            empty_metrics,
        )
        if not isinstance(trace, list) or not trace:
            self.failed_steps.append("trace_contract")
            trace = minimal_fallback_trace()
            metrics = minimal_fallback_metrics()
        if not isinstance(metrics, dict):
            self.failed_steps.append("metrics_contract")
            metrics = minimal_fallback_metrics()
        if not isinstance(provenance, dict):
            self.failed_steps.append("provenance_contract")
            provenance = {}
        metrics = dict(metrics)
        metrics["outcome"] = str(outcome)
        metrics["final_phase"] = str(final_phase)
        metrics["error_code"] = str(error_code)
        metrics["fallback_used"] = str(outcome) == "fallback"
        metrics["terminalizer_failed_steps"] = list(self.failed_steps)
        return {
            "final_response": response,
            "trace": trace,
            "run_metrics": metrics,
            "provenance": provenance,
        }


def minimal_fallback_result() -> dict[str, Any]:
    return {
        "final_response": MINIMAL_FALLBACK_RESPONSE,
        "trace": minimal_fallback_trace(),
        "run_metrics": minimal_fallback_metrics(),
        "provenance": {},
    }
def minimal_fallback_metrics() -> dict[str, Any]:
    return {
        "outcome": "fallback",
        "final_phase": "fallback_completed",
        "error_code": "all_candidates_failed",
        "fallback_used": True,
    }


def minimal_fallback_trace() -> list[dict[str, Any]]:
    events = (
        (
            "session_started",
            {"request_source": "official_client_injected"},
        ),
        (
            "fallback_used",
            {
                "reason": "all_candidates_failed",
                "error_code": "all_candidates_failed",
                "failed_phase": "created",
            },
        ),
        (
            "closed_loop_health",
            minimal_closed_loop_health(),
        ),
        (
            "budget_summary",
            {"outcome": "fallback"},
        ),
        (
            "run_completed",
            {
                "outcome": "fallback",
                "error_code": "all_candidates_failed",
                "final_phase": "fallback_completed",
            },
        ),
    )
    return [
        {
            "schema_version": TRACE_SCHEMA_VERSION,
            "seq": index,
            "elapsed_ms": 0,
            "event": event,
            "stage": EVENT_STAGES[event],
            **details,
        }
        for index, (event, details) in enumerate(events, start=1)
    ]
