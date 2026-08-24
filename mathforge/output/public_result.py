from __future__ import annotations

import json
from typing import Any

from mathforge.harness.events import TRACE_SCHEMA_VERSION
from mathforge.harness.terminalizer import MINIMAL_FALLBACK_RESPONSE
from mathforge.harness.trace import validate_trace_v2
from mathforge.output.judge_trace import (
    JUDGE_TRACE_SCHEMA_VERSION,
    JudgeTraceLimits,
    project_judge_trace,
    validate_judge_trace,
)
from mathforge.output.official_trace import (
    is_official_trace,
    minimal_official_trace,
    project_official_trace,
    validate_official_trace,
)
from mathforge.output.deterministic_formatter import exact_final_answer
from mathforge.parsing.answer_salvage import salvage_any_answer


PUBLIC_STATUSES = frozenset({"success", "failed", "timeout"})
_OUTCOME_TO_STATUS = {
    "primary": "success",
    "success": "success",
    "fallback": "failed",
    "error": "failed",
    "failed": "failed",
    "timeout": "timeout",
}


def build_public_result(identifier: int | str | None, result: dict) -> dict:
    if not isinstance(result, dict):
        result = {}
    supplied_response = result.get("final_response", "")
    final_response = (
        supplied_response.strip()
        if isinstance(supplied_response, str) and supplied_response.strip()
        else MINIMAL_FALLBACK_RESPONSE
    )
    final_response = exact_final_answer(final_response, "expression")
    trace = result.get("trace", [])
    if not isinstance(trace, list):
        trace = []
    limits = JudgeTraceLimits.from_mapping(
        result.get("_public_output_limits")
        if isinstance(result, dict)
        else None
    )
    final_response = _trim_final_response(
        final_response,
        limits.final_response_max_chars,
    )
    status = _safe_public_status(result, trace)
    trace_valid = True
    try:
        if any(
            isinstance(event, dict)
            and event.get("schema_version") == TRACE_SCHEMA_VERSION
            for event in trace
        ):
            validate_trace_v2(trace, final_response=final_response)
            trace = project_judge_trace(
                trace,
                final_response=final_response,
                limits=limits,
            )
            validate_judge_trace(
                trace,
                final_response=final_response,
                limits=limits,
            )
            trace = project_official_trace(
                trace,
                final_response=final_response,
                limits=limits,
            )
        elif any(
            isinstance(event, dict)
            and event.get("schema_version") == JUDGE_TRACE_SCHEMA_VERSION
            for event in trace
        ):
            validate_judge_trace(
                trace,
                final_response=final_response,
                limits=limits,
            )
            trace = project_official_trace(
                trace,
                final_response=final_response,
                limits=limits,
            )
        elif is_official_trace(trace):
            validate_official_trace(trace, limits=limits)
        else:
            trace_valid = False
    except Exception:
        trace_valid = False
    if not trace_valid:
        status = "timeout" if status == "timeout" else "failed"
        trace = minimal_official_trace(
            outcome=_status_outcome(status),
            error_code="public_trace_replaced",
        )
    payload = {
        "id": identifier,
        "status": status,
        "final_response": final_response,
        "trace": trace,
    }
    if serialized_public_result_bytes(payload) > limits.public_result_max_bytes:
        payload["status"] = "failed"
        payload["trace"] = minimal_official_trace(
            outcome="fallback",
            error_code="public_trace_trimmed",
        )
        if serialized_public_result_bytes(payload) > limits.public_result_max_bytes:
            payload["final_response"] = _trim_to_utf8_budget(
                payload["final_response"],
                max(1, limits.public_result_max_bytes - 256),
            )
    return payload


def serialized_public_result_bytes(payload: dict[str, Any]) -> int:
    return len(
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
        ).encode("utf-8")
    ) + 1


def _public_status(result: dict, trace: list) -> str:
    explicit = result.get("status")
    if explicit is not None and explicit not in PUBLIC_STATUSES:
        raise ValueError("public result status is invalid")
    outcome = ""
    metrics = result.get("run_metrics")
    if isinstance(metrics, dict):
        outcome = str(metrics.get("outcome", ""))
    if not outcome:
        terminal = next(
            (
                event
                for event in reversed(trace)
                if isinstance(event, dict)
                and event.get("event") == "run_completed"
            ),
            {},
        )
        outcome = str(terminal.get("outcome", ""))
    derived = _OUTCOME_TO_STATUS.get(outcome)
    if explicit is not None and derived is not None and explicit != derived:
        raise ValueError("public result status conflicts with terminal outcome")
    if explicit is not None:
        return explicit
    return derived or "failed"


def _safe_public_status(result: dict, trace: list) -> str:
    try:
        return _public_status(result, trace)
    except (TypeError, ValueError):
        return "failed"


def _status_outcome(status: str) -> str:
    return {
        "success": "primary",
        "timeout": "timeout",
    }.get(status, "fallback")


def _trim_final_response(response: str, max_chars: int) -> str:
    if len(response) <= max_chars:
        return response
    salvaged = salvage_any_answer((response,))
    if salvaged:
        salvaged = exact_final_answer(salvaged, "expression")
    if not salvaged or len(salvaged) > max_chars:
        salvaged = MINIMAL_FALLBACK_RESPONSE
    separator = "\n\n"
    prefix_budget = max_chars - len(separator) - len(salvaged)
    if prefix_budget <= 0:
        return salvaged[:max_chars]
    return response[:prefix_budget].rstrip() + separator + salvaged


def _trim_to_utf8_budget(response: str, max_bytes: int) -> str:
    salvaged = salvage_any_answer((response,)) or MINIMAL_FALLBACK_RESPONSE
    salvaged = exact_final_answer(salvaged, "expression")
    if len(salvaged.encode("utf-8")) <= max_bytes:
        return salvaged
    return MINIMAL_FALLBACK_RESPONSE


def identifier_from_metadata(metadata: dict[str, Any]) -> int | str | None:
    identifier = metadata.get("id", metadata.get("idx"))
    return identifier if isinstance(identifier, (int, str)) else None
