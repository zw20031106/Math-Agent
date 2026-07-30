from __future__ import annotations

import json
from typing import Any

from mathforge.harness.events import TRACE_SCHEMA_VERSION
from mathforge.harness.trace import validate_trace_v2
from mathforge.output.judge_trace import (
    JUDGE_TRACE_SCHEMA_VERSION,
    JudgeTraceLimits,
    project_judge_trace,
    validate_judge_trace,
)


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
    final_response = result.get("final_response", "")
    trace = result.get("trace", [])
    if not isinstance(final_response, str) or not final_response.strip():
        raise ValueError("public result requires a non-empty final_response")
    if not isinstance(trace, list):
        raise ValueError("public result requires a list-valued trace")
    limits = JudgeTraceLimits.from_mapping(
        result.get("_public_output_limits")
        if isinstance(result, dict)
        else None
    )
    if len(final_response) > limits.final_response_max_chars:
        raise ValueError("final_response exceeds configured character budget")
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
    status = _public_status(result, trace)
    payload = {
        "id": identifier,
        "status": status,
        "final_response": final_response,
        "trace": trace,
    }
    if serialized_public_result_bytes(payload) > limits.public_result_max_bytes:
        raise ValueError("serialized public result exceeds configured byte budget")
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


def identifier_from_metadata(metadata: dict[str, Any]) -> int | str | None:
    identifier = metadata.get("id", metadata.get("idx"))
    return identifier if isinstance(identifier, (int, str)) else None
