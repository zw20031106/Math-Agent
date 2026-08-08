from __future__ import annotations

from typing import Any, Iterable

from mathforge.harness.transport import SAFE_TRANSPORT_FAILURE_CODES


_AGGREGATE_FAILURE_CODES = frozenset(
    {"all_candidates_failed", "case_execution_failed", "fallback"}
)


def build_closed_loop_health(
    internal_events: Iterable[dict[str, Any]],
    *,
    budget: dict[str, Any] | None,
    selected_candidate_id: str,
    outcome: str,
    error_code: str = "",
) -> dict[str, Any]:
    """Build a deterministic, public-safe summary of harness closure quality."""

    events = list(internal_events)
    by_name = _events_by_name(events)
    budget_data = budget if isinstance(budget, dict) else {}
    arbitration = _last(by_name, "candidate_arbitrated")
    final_event = _last(by_name, "final_answer_selected")
    selected_id = (
        str(selected_candidate_id)
        if outcome in {"primary", "success"}
        and isinstance(final_event, dict)
        else ""
    )

    root_failure_codes = _root_failure_codes(
        events,
        budget_data,
        error_code=error_code,
    )
    primary = _primary_status(by_name)
    shadow = _shadow_status(_last(by_name, "shadow_probe_completed"))
    alternatives_started = sum(
        str(event.get("role", "")) == "AlternativeSolver"
        for event in by_name.get("candidate_generation_started", [])
    )
    viable_count = len(_string_list(arbitration, "viable_candidates"))

    hard_evidence = _hard_evidence_status(by_name, selected_id)
    proof_status, required_obligations = _proof_status(by_name, selected_id)
    cross_review = _cross_review_status(
        _last(by_name, "candidate_conflict_matrix"),
        _last(by_name, "verifier_completed"),
    )
    repair = _repair_status(by_name)
    answer_available = bool(
        selected_id
        and isinstance(final_event, dict)
        and str(final_event.get("candidate_id", selected_id)) == selected_id
    )
    selection_basis = (
        str(arbitration.get("selection_reason", ""))
        if isinstance(arbitration, dict)
        else ""
    )

    degradation_reasons: list[str] = []
    if isinstance(arbitration, dict):
        if arbitration.get("selection_quality") == "degraded_shadow_only":
            degradation_reasons.append("shadow_only_selection")
    if root_failure_codes:
        degradation_reasons.extend(
            f"model_dispatch:{code}" for code in root_failure_codes
        )
    verifier = _last(by_name, "verifier_completed")
    if isinstance(verifier, dict) and verifier.get("status") in {
        "unavailable",
        "unknown",
    }:
        degradation_reasons.append(
            f"verifier_{verifier.get('status')}"
        )
    if proof_status == "incomplete":
        degradation_reasons.append("proof_incomplete")
    if hard_evidence in {"failed", "unknown"}:
        degradation_reasons.append(f"hard_evidence_{hard_evidence}")

    if outcome == "timeout":
        health = "timeout"
    elif outcome == "interrupted":
        health = "interrupted"
    elif not answer_available or not selected_id or outcome in {
        "fallback",
        "error",
        "failed",
    }:
        health = "failed"
    elif degradation_reasons:
        health = "degraded"
    else:
        health = "healthy"

    return {
        "health": health,
        "model_dispatch": {
            "used": _nonnegative_int(
                budget_data.get(
                    "used_calls",
                    budget_data.get("model_calls", 0),
                )
            ),
            "limit": _nonnegative_int(budget_data.get("max_calls", 0)),
            "transport_attempts": _nonnegative_int(
                budget_data.get("transport_attempts", 0)
            ),
            "root_failure_codes": root_failure_codes,
        },
        "candidate_flow": {
            "primary": primary,
            "shadow": shadow,
            "alternatives_started": alternatives_started,
            "viable_count": viable_count,
            "selected_candidate_id": selected_id,
        },
        "verification_flow": {
            "hard_evidence": hard_evidence,
            "required_obligations": required_obligations,
            "cross_review": cross_review,
            "repair": repair,
        },
        "closure": {
            "answer_available": answer_available,
            "proof_status": proof_status,
            "selection_basis": selection_basis,
            "degradation_reasons": list(dict.fromkeys(degradation_reasons)),
        },
    }


def minimal_closed_loop_health(
    *,
    health: str = "failed",
    root_failure_code: str = "all_candidates_failed",
) -> dict[str, Any]:
    return {
        "health": health,
        "model_dispatch": {
            "used": 0,
            "limit": 0,
            "transport_attempts": 0,
            "root_failure_codes": (
                [root_failure_code] if root_failure_code else []
            ),
        },
        "candidate_flow": {
            "primary": "not_started",
            "shadow": "unsupported",
            "alternatives_started": 0,
            "viable_count": 0,
            "selected_candidate_id": "",
        },
        "verification_flow": {
            "hard_evidence": "not_available",
            "required_obligations": 0,
            "cross_review": "not_requested",
            "repair": "not_requested",
        },
        "closure": {
            "answer_available": False,
            "proof_status": "not_available",
            "selection_basis": "",
            "degradation_reasons": (
                [root_failure_code] if root_failure_code else []
            ),
        },
    }


def _events_by_name(
    events: Iterable[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        if isinstance(event, dict):
            grouped.setdefault(str(event.get("event", "")), []).append(event)
    return grouped


def _last(
    by_name: dict[str, list[dict[str, Any]]],
    name: str,
) -> dict[str, Any] | None:
    events = by_name.get(name, [])
    return events[-1] if events else None


def _primary_status(
    by_name: dict[str, list[dict[str, Any]]],
) -> str:
    candidates = [
        event
        for event in by_name.get("candidate_generated", [])
        if event.get("role") == "PrimarySolver"
    ]
    if candidates:
        return (
            "success"
            if candidates[-1].get("parse_tier") == "strict"
            else "recovered"
        )
    starts = any(
        event.get("role") == "PrimarySolver"
        for event in by_name.get("candidate_generation_started", [])
    )
    return "failed" if starts else "not_started"


def _shadow_status(event: dict[str, Any] | None) -> str:
    status = str(event.get("status", "")) if event else ""
    if status == "exact":
        return "exact"
    if status in {"partial", "verified_numeric"}:
        return "partial"
    if status == "failed":
        return "failed"
    return "unsupported"


def _hard_evidence_status(
    by_name: dict[str, list[dict[str, Any]]],
    selected_id: str,
) -> str:
    if not selected_id:
        return "not_available"
    gate = _last(by_name, "hard_evidence_gate")
    if not gate:
        return "not_available"
    if selected_id in _string_list(gate, "accepted"):
        return "passed"
    if selected_id in _string_list(gate, "rejected"):
        return "failed"
    return "unknown"


def _proof_status(
    by_name: dict[str, list[dict[str, Any]]],
    selected_id: str,
) -> tuple[str, int]:
    if not selected_id:
        return "not_available", 0
    finalized = _last(by_name, "proof_status_finalized")
    if finalized:
        statuses = finalized.get("statuses", [])
        if isinstance(statuses, list):
            selected = next(
                (
                    item
                    for item in statuses
                    if isinstance(item, dict)
                    and str(item.get("candidate_id", "")) == selected_id
                ),
                None,
            )
            if selected is not None:
                status = str(selected.get("status", "incomplete"))
                if status in {
                    "complete_hard",
                    "complete_audited",
                    "incomplete",
                    "failed",
                }:
                    return status, 0
    gate = _last(by_name, "proof_completion_gate")
    if not gate:
        graph_event = _last(by_name, "proof_graph_completed")
        graph = (
            graph_event.get("graph", {})
            if isinstance(graph_event, dict)
            else {}
        )
        summary = graph.get("summary", {}) if isinstance(graph, dict) else {}
        if not isinstance(summary, dict) or not summary:
            return "not_available", 0
        unresolved = _nonnegative_int(
            summary.get("unresolved_required_obligations", 0)
        )
        return ("complete_hard" if unresolved == 0 else "incomplete"), 0
    decisions = gate.get("decisions", [])
    if not isinstance(decisions, list):
        return "not_available", 0
    decision = next(
        (
            item
            for item in decisions
            if isinstance(item, dict)
            and str(item.get("candidate_id", "")) == selected_id
        ),
        {},
    )
    obligations = decision.get("obligations", [])
    if not isinstance(obligations, list):
        obligations = []
    required = sum(
        isinstance(item, dict) and bool(item.get("required", False))
        for item in obligations
    )
    status = str(decision.get("status", ""))
    if not decision:
        graph_event = _last(by_name, "proof_graph_completed")
        graph = (
            graph_event.get("graph", {})
            if isinstance(graph_event, dict)
            else {}
        )
        summary = graph.get("summary", {}) if isinstance(graph, dict) else {}
        if not isinstance(summary, dict) or not summary:
            return "not_available", 0
        unresolved = _nonnegative_int(
            summary.get("unresolved_required_obligations", 0)
        )
        return ("complete_hard" if unresolved == 0 else "incomplete"), 0
    return (
        status
        if status in {
            "complete_hard",
            "complete_audited",
            "incomplete",
            "failed",
        }
        else "incomplete",
        required,
    )


def _cross_review_status(
    event: dict[str, Any] | None,
    verifier: dict[str, Any] | None,
) -> str:
    if not event:
        return "not_requested"
    matrix = event.get("matrix", {})
    if not isinstance(matrix, dict):
        return "unknown"
    candidate_ids = matrix.get("candidate_ids", [])
    if not isinstance(candidate_ids, list) or len(candidate_ids) < 2:
        return "not_requested"
    conflicts = matrix.get("conflicts", [])
    if not isinstance(conflicts, list):
        return "unknown"
    conflict_exists = any(
        isinstance(item, dict)
        and (
            item.get("answer_conflict") is True
            or item.get("assumption_conflict") is True
            or item.get("critical_claim_conflict") is True
        )
        for item in conflicts
    )
    if not conflict_exists:
        return "passed"
    if not isinstance(verifier, dict):
        return "unreviewed"
    unreviewed = verifier.get("unreviewed_targets", [])
    if isinstance(unreviewed, list) and unreviewed:
        return "incomplete"
    return (
        "reviewed"
        if verifier.get("reviewed_targets")
        else "unreviewed"
    )


def _repair_status(
    by_name: dict[str, list[dict[str, Any]]],
) -> str:
    repairs = by_name.get("repair_completed", [])
    if repairs:
        return (
            "rolled_back"
            if repairs[-1].get("rolled_back") is True
            else "accepted"
        )
    gate = _last(by_name, "repair_actionability_gate")
    if gate and not gate.get("actionable_claims"):
        return "not_actionable"
    return "not_requested"


def _root_failure_codes(
    events: Iterable[dict[str, Any]],
    budget: dict[str, Any],
    *,
    error_code: str,
) -> list[str]:
    codes: list[str] = []
    records = budget.get("model_call_records", [])
    if isinstance(records, list):
        codes.extend(
            str(record.get("failure_code", ""))
            for record in records
            if isinstance(record, dict) and record.get("failure_code")
        )
    codes.extend(
        str(event.get("reason", ""))
        for event in events
        if event.get("event") == "candidate_generation_failed"
        and event.get("reason")
    )
    if error_code:
        codes.append(str(error_code))
    safe_specific = [
        code
        for code in codes
        if code in SAFE_TRANSPORT_FAILURE_CODES
    ]
    if safe_specific:
        return list(dict.fromkeys(safe_specific))
    return list(
        dict.fromkeys(
            code
            for code in codes
            if code and code not in _AGGREGATE_FAILURE_CODES
        )
    ) or (
        [str(error_code)]
        if error_code
        else []
    )


def _string_list(event: dict[str, Any] | None, key: str) -> list[str]:
    values = event.get(key, []) if event else []
    if not isinstance(values, list):
        return []
    return [str(value) for value in values]


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
