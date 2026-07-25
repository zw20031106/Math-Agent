from __future__ import annotations

from copy import deepcopy
from typing import Any

from mathforge.harness.events import TRACE_SCHEMA_VERSION
from mathforge.harness.trace import validate_trace_v2


PUBLIC_STATUSES = frozenset({"success", "failed", "timeout"})
_OUTCOME_TO_STATUS = {
    "primary": "success",
    "success": "success",
    "fallback": "failed",
    "error": "failed",
    "failed": "failed",
    "timeout": "timeout",
}
_PUBLIC_TRACE_OMISSIONS = frozenset(
    {
        "phase_transition",
        "context_view_built",
        "candidate_fanout_completed",
        "primary_completed",
        "finalization_completed",
        "compression_validated",
        "candidate_final_states",
    }
)
_SESSION_FIELDS = (
    "session_id",
    "request_fingerprint",
    "config_profile",
    "config_schema_version",
    "config_hash",
    "prompt_hash",
    "skill_hash",
    "rag_hash",
    "tool_hash",
    "code_commit",
    "code_dirty",
    "requested_model",
    "request_source",
    "response_model_observable",
    "thinking_mode_observable",
    "provenance_hash",
)
_ROUTE_FIELDS = (
    "primary_subject",
    "auxiliary_subject",
    "risk_level",
    "routing_confidence",
    "complexity_flags",
    "selected_skills",
    "selected_tools",
    "method_families",
    "routing_reasons",
)
_BUDGET_FIELDS = (
    "max_calls",
    "used_calls",
    "model_calls",
    "prompt_tokens",
    "requested_output_tokens",
    "observed_output_tokens",
    "output_chars",
    "model_call_elapsed_seconds",
    "model_call_timeout_count",
    "used_tool_calls",
    "used_evidence_records",
    "elapsed_seconds",
    "remaining_seconds",
    "deadline_phase",
    "outcome",
)
_MODEL_CALL_RECORD_FIELDS = (
    "stage",
    "prompt_tokens",
    "max_output_tokens",
    "status",
    "observed_output_tokens",
    "output_chars",
    "elapsed_seconds",
)


def build_public_result(identifier: int | str | None, result: dict) -> dict:
    final_response = result.get("final_response", "")
    trace = result.get("trace", [])
    if not isinstance(final_response, str) or not final_response.strip():
        raise ValueError("public result requires a non-empty final_response")
    if not isinstance(trace, list):
        raise ValueError("public result requires a list-valued trace")
    if any(
        isinstance(event, dict)
        and event.get("schema_version") == TRACE_SCHEMA_VERSION
        for event in trace
    ):
        validate_trace_v2(trace, final_response=final_response)
        trace = _public_trace(trace, final_response)
    status = _public_status(result, trace)
    return {
        "id": identifier,
        "status": status,
        "final_response": final_response,
        "trace": trace,
    }


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


def _public_trace(trace: list[dict[str, Any]], final_response: str) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for event in trace:
        name = str(event.get("event", ""))
        if name in _PUBLIC_TRACE_OMISSIONS:
            continue
        if name == "background_tail_audit" and not event.get("started"):
            continue
        if name == "session_started":
            item = _select_event_fields(event, _SESSION_FIELDS)
        elif name == "route_planned":
            item = _select_event_fields(event, _ROUTE_FIELDS)
        elif name == "skills_selected":
            item = _compact_skills_event(event)
        elif name == "budget_summary":
            item = _compact_budget_event(event)
        else:
            item = deepcopy(event)
        projected.append(item)
    for sequence, event in enumerate(projected, start=1):
        event["seq"] = sequence
    validate_trace_v2(projected, final_response=final_response)
    return projected


def _select_event_fields(
    event: dict[str, Any],
    fields: tuple[str, ...],
) -> dict[str, Any]:
    item = {
        key: deepcopy(event[key])
        for key in ("schema_version", "seq", "elapsed_ms", "event", "stage")
    }
    item.update(
        {
            key: deepcopy(event[key])
            for key in fields
            if key in event
        }
    )
    return item


def _compact_skills_event(event: dict[str, Any]) -> dict[str, Any]:
    item = _select_event_fields(event, ("skill_fingerprint",))
    grouped: dict[tuple[str, str, str], list[str]] = {}
    for skill in event.get("skills", []):
        if not isinstance(skill, dict):
            continue
        skill_key = (
            str(skill.get("name", "")),
            str(skill.get("version", "")),
            str(skill.get("reason", "")),
        )
        roles = skill.get("roles", [skill.get("role", "")])
        if skill_key[0] and isinstance(roles, list):
            grouped.setdefault(skill_key, []).extend(
                str(role) for role in roles if role
            )
    item["skills"] = [
        {
            "name": name,
            "version": version,
            "reason": reason,
            "roles": sorted(set(roles)),
        }
        for (name, version, reason), roles in grouped.items()
    ]
    for detail_key in ("omitted_by_role", "unknown_by_role"):
        if event.get(detail_key):
            item[detail_key] = deepcopy(event[detail_key])
    return item


def _compact_budget_event(event: dict[str, Any]) -> dict[str, Any]:
    item = _select_event_fields(event, _BUDGET_FIELDS)
    records = event.get("model_call_records", [])
    if isinstance(records, list):
        item["model_call_records"] = [
            {
                key: deepcopy(record[key])
                for key in _MODEL_CALL_RECORD_FIELDS
                if isinstance(record, dict) and key in record
            }
            for record in records
            if isinstance(record, dict)
        ]
    return item


def identifier_from_metadata(metadata: dict[str, Any]) -> int | str | None:
    identifier = metadata.get("id", metadata.get("idx"))
    return identifier if isinstance(identifier, (int, str)) else None
