from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from mathforge.harness.schemas import CandidateSolution, EvidenceRecord
from mathforge.harness.transport import SAFE_TRANSPORT_FAILURE_CODES
from mathforge.verification.evidence import is_fatal_hard_failure


CASE_SUMMARY_SCHEMA_VERSION = "1.0"
_ROLE_BY_STAGE = {
    "router": "RouterPlanner",
    "primary": "PrimarySolver",
    "alternative": "AlternativeSolver",
    "lemma": "LemmaCurator",
    "verifier": "VerifierSkeptic",
    "repair": "RepairAgent",
    "finalizer": "LLMFinalizer",
}


def build_transport_summary(
    model_call_records: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    calls: list[dict[str, Any]] = []
    for call_index, record in enumerate(model_call_records, start=1):
        failure_code = str(record.get("failure_code", ""))
        stage = str(record.get("stage", ""))
        if failure_code not in SAFE_TRANSPORT_FAILURE_CODES:
            failure_code = "unknown_provider_failure" if failure_code else ""
        calls.append(
            {
                "call_index": call_index,
                "role": _ROLE_BY_STAGE.get(stage, stage),
                "stage": stage,
                "status": str(record.get("status", "unknown")),
                "attempts": max(
                    0,
                    _nonnegative_int(record.get("transport_attempts", 0)),
                ),
                "failure_code": failure_code,
                "response_validation": str(
                    record.get("response_validation", "not_applicable")
                ),
                "elapsed_seconds": _nonnegative_float(
                    record.get("elapsed_seconds", 0.0)
                ),
                "queue_elapsed_seconds": _nonnegative_float(
                    record.get("queue_elapsed_seconds", 0.0)
                ),
                "execution_elapsed_seconds": _nonnegative_float(
                    record.get("execution_elapsed_seconds", 0.0)
                ),
                "output_chars": _nonnegative_int(
                    record.get("output_chars", 0)
                ),
            }
        )
    failure_codes = Counter(
        call["failure_code"] for call in calls if call["failure_code"]
    )
    return {
        "calls": calls,
        "summary": {
            "calls": len(calls),
            "completed": sum(call["status"] == "completed" for call in calls),
            "failed": sum(call["status"] == "failed" for call in calls),
            "timeout": sum(call["status"] == "timeout" for call in calls),
            "attempts": sum(call["attempts"] for call in calls),
            "failure_codes": dict(sorted(failure_codes.items())),
        },
    }


def build_case_trace_summary(
    *,
    candidates: Iterable[CandidateSolution],
    evidence: Iterable[EvidenceRecord],
    candidate_states: Iterable[dict[str, Any]],
    internal_events: Iterable[dict[str, Any]],
    model_call_records: Iterable[dict[str, Any]],
    selected_candidate_id: str,
    proof_graph_summary: dict[str, Any],
    outcome: str,
) -> dict[str, Any]:
    candidate_items = list(candidates)
    evidence_items = [
        record
        for record in evidence
        if record.transaction_status == "active"
    ]
    event_items = list(internal_events)
    state_by_id = {
        str(item.get("candidate_id", "")): item
        for item in candidate_states
        if isinstance(item, dict) and item.get("candidate_id")
    }
    transport = build_transport_summary(model_call_records)

    candidate_summaries = []
    for candidate in sorted(candidate_items, key=lambda item: item.candidate_id):
        records = [
            record
            for record in evidence_items
            if record.candidate_id == candidate.candidate_id
        ]
        state = state_by_id.get(candidate.candidate_id, {})
        candidate_summaries.append(
            {
                "candidate_id": candidate.candidate_id,
                "role": candidate.role,
                "method": candidate.method,
                "version": candidate.version,
                "complete": bool(
                    candidate.final_answer.strip()
                    and candidate.public_solution_steps
                    and candidate.claims
                ),
                "final_answer": candidate.final_answer,
                "status": str(state.get("status", "generated")),
                "reason_codes": sorted(
                    str(code) for code in state.get("reason_codes", [])
                ),
                "claim_count": len(candidate.claims),
                "evidence": {
                    status: sum(
                        record.status == status for record in records
                    )
                    for status in ("pass", "fail", "unknown", "error")
                },
                "fatal_evidence_ids": sorted(
                    record.evidence_id
                    for record in records
                    if is_fatal_hard_failure(record)
                ),
            }
        )

    repairs = [
        event for event in event_items if event.get("event") == "repair_completed"
    ]
    role_calls = Counter(
        str(call["role"]) for call in transport["calls"] if call["role"]
    )
    evidence_counts = Counter(record.status for record in evidence_items)
    decision_path = [
        f"generated:{len(candidate_items)}",
        (
            "evidence:"
            f"pass={evidence_counts['pass']},"
            f"fail={evidence_counts['fail']},"
            f"unknown={evidence_counts['unknown']},"
            f"error={evidence_counts['error']}"
        ),
        (
            "repair:"
            f"attempted={len(repairs)},"
            f"accepted={sum(event.get('accepted') is True for event in repairs)}"
        ),
        f"selected:{selected_candidate_id or 'none'}",
        f"outcome:{outcome}",
    ]
    return {
        "schema_version": CASE_SUMMARY_SCHEMA_VERSION,
        "outcome": outcome,
        "roles_called": [
            {"role": role, "calls": count}
            for role, count in sorted(role_calls.items())
        ],
        "candidates": candidate_summaries,
        "selected_candidate_id": selected_candidate_id,
        "selection_reason": (
            "hard-evidence gate followed by lexicographic arbitration"
            if selected_candidate_id
            else "no candidate reached final selection"
        ),
        "evidence": {
            status: evidence_counts[status]
            for status in ("pass", "fail", "unknown", "error")
        },
        "repairs": {
            "attempted": len(repairs),
            "accepted": sum(
                event.get("accepted") is True for event in repairs
            ),
            "rolled_back": sum(
                event.get("rolled_back") is True for event in repairs
            ),
            "reason_codes": sorted(
                {
                    str(event.get("reason", ""))
                    for event in repairs
                    if event.get("reason")
                }
            ),
        },
        "transport": transport["summary"],
        "proof_graph": proof_graph_summary,
        "decision_path": decision_path,
    }


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _nonnegative_float(value: Any) -> float:
    try:
        return round(max(0.0, float(value)), 6)
    except (TypeError, ValueError):
        return 0.0
