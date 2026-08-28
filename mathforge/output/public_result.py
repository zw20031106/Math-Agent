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
PUBLIC_RESULT_FIELDS = frozenset({"id", "status", "final_response", "trace"})
_ALLOWED_CONTROL_CHARS = frozenset({"\t", "\n", "\r"})
_OUTCOME_TO_STATUS = {
    "primary": "success",
    "success": "success",
    "fallback": "failed",
    "error": "failed",
    "failed": "failed",
    "timeout": "timeout",
}


class PublicContractError(ValueError):
    """Raised when the immutable four-field participant contract is invalid."""


def build_public_result(identifier: int | str | None, result: dict) -> dict:
    if not isinstance(result, dict):
        result = {}
    supplied_response = result.get("final_response", "")
    final_response = (
        supplied_response.strip()
        if isinstance(supplied_response, str) and supplied_response.strip()
        else MINIMAL_FALLBACK_RESPONSE
    )
    final_response = exact_final_answer(
        _sanitize_public_text(final_response),
        "expression",
    )
    trace = result.get("trace", [])
    if not isinstance(trace, list):
        trace = []
    trace = _sanitize_public_value(trace)
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
    try:
        validate_public_result(payload)
    except PublicContractError:
        # A trace serialization failure is a publication failure under the
        # official contract.  The internal run outcome and evaluation artifact
        # remain untouched; only this public projection is fail-closed.
        payload = {
            "id": identifier,
            "status": "failed",
            "final_response": _sanitize_public_text(
                exact_final_answer(final_response, "expression")
                or MINIMAL_FALLBACK_RESPONSE
            ),
            "trace": minimal_official_trace(
                outcome="fallback",
                error_code="public_contract_invalid",
            ),
        }
        validate_public_result(payload)
    return payload


def validate_public_result(payload: dict[str, Any]) -> None:
    """Validate the exact public schema and reject unsafe control characters."""

    if not isinstance(payload, dict):
        raise PublicContractError("public result must be an object")
    if set(payload) != PUBLIC_RESULT_FIELDS:
        raise PublicContractError("public result must contain exactly four fields")
    identifier = payload.get("id")
    if identifier is not None and not isinstance(identifier, (int, str)):
        raise PublicContractError("public result id has invalid type")
    if isinstance(identifier, str):
        _validate_public_text(identifier)
    if payload.get("status") not in PUBLIC_STATUSES:
        raise PublicContractError("public result status is invalid")
    response = payload.get("final_response")
    if not isinstance(response, str) or not response.strip():
        raise PublicContractError("public final_response must be non-empty")
    trace = payload.get("trace")
    if not isinstance(trace, list):
        raise PublicContractError("public trace must be a list")
    _validate_public_text(response)
    _validate_public_value(trace)
    try:
        json.dumps(payload, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise PublicContractError("public result is not JSON serializable") from error


def serialized_public_result_bytes(payload: dict[str, Any]) -> int:
    return len(
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
        ).encode("utf-8")
    ) + 1


def _sanitize_public_text(value: str) -> str:
    return "".join(
        character
        if character in _ALLOWED_CONTROL_CHARS or ord(character) >= 32
        else " "
        for character in str(value or "")
    )


def _sanitize_public_value(value: Any) -> Any:
    if isinstance(value, str):
        return _sanitize_public_text(value)
    if isinstance(value, list):
        return [_sanitize_public_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_public_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _sanitize_public_value(item)
            for key, item in value.items()
        }
    return value


def _validate_public_text(value: str) -> None:
    if any(
        ord(character) < 32 and character not in _ALLOWED_CONTROL_CHARS
        for character in value
    ):
        raise PublicContractError("public output contains a control character")


def _validate_public_value(value: Any) -> None:
    if isinstance(value, str):
        _validate_public_text(value)
        return
    if isinstance(value, list):
        for item in value:
            _validate_public_value(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _validate_public_text(str(key))
            _validate_public_value(item)


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
