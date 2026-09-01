from __future__ import annotations

import json
import re
from typing import Any, Mapping

from mathforge.output.judge_trace import JudgeTraceLimits


_STEP_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_OPTIONAL_STEPS = ("repair", "cross_review", "candidate_generation", "model_call")


class OfficialTraceIntegrityError(ValueError):
    pass


def project_official_trace(
    judge_trace: list[dict[str, Any]],
    *,
    final_response: str,
    limits: Mapping[str, Any] | JudgeTraceLimits | None = None,
) -> list[dict[str, str]]:
    """Project the internal Judge Trace into the official step/content contract."""

    active_limits = _limits(limits)
    by_name = _events_by_name(judge_trace)
    items: list[dict[str, str]] = []

    def add(step: str, content: str) -> None:
        normalized = " ".join(str(content or "").split()).strip()
        if not normalized:
            return
        items.append(
            {
                "step": step,
                "content": _clip(
                    normalized,
                    max(256, active_limits.judge_trace_event_max_chars - 128),
                ),
            }
        )

    overview = _last(by_name, "workflow_overview")
    overview_steps = overview.get("steps", []) if overview else []
    plan_parts = [
        str(item.get("summary", "")).strip()
        for item in overview_steps
        if isinstance(item, dict)
        and item.get("phase") in {"problem_understanding", "planning"}
        and str(item.get("summary", "")).strip()
    ]
    route = _last(by_name, "route_planned") or {}
    if not plan_parts and route:
        subject = route.get("primary_subject", route.get("primary_domain", "unknown"))
        plan_parts.append(f"Router selected the mathematical route for {subject}.")
    add(
        "plan",
        " ".join(plan_parts)
        or "The problem was parsed, and a public reasoning route was prepared.",
    )

    process = _last(by_name, "solution_process") or {}
    reasoning_parts: list[str] = []
    method = str(process.get("method", "")).strip()
    if method:
        reasoning_parts.append(f"Method: {method}.")
    public_steps = process.get("steps", [])
    if isinstance(public_steps, list):
        reasoning_parts.extend(
            f"Step {index}: {str(statement).strip()}"
            for index, statement in enumerate(public_steps, start=1)
            if str(statement).strip()
        )
    conclusion = str(process.get("conclusion", "")).strip()
    if conclusion:
        reasoning_parts.append(f"Conclusion: {conclusion}")
    add(
        "reasoning",
        " ".join(reasoning_parts)
        or "No complete public mathematical derivation was available.",
    )

    candidate_event = _last(by_name, "candidate_summaries") or {}
    candidates = candidate_event.get("candidates", [])
    if isinstance(candidates, list) and candidates:
        viable = [
            item
            for item in candidates
            if isinstance(item, dict)
            and item.get("status") in {"selected", "viable_not_selected"}
        ]
        methods = list(
            dict.fromkeys(
                str(item.get("method_family", "")).strip()
                for item in viable
                if str(item.get("method_family", "")).strip()
            )
        )
        candidate_parts = []
        for item in viable:
            role = str(item.get("role", "candidate")).strip() or "candidate"
            method_name = str(item.get("method_family", "unknown")).strip() or "unknown"
            if item.get("selected") is True:
                answer_summary = "selected; answer shown in the reasoning step"
            else:
                public_answer = str(item.get("public_final_answer", "")).strip()
                answer_summary = (
                    f"answer {public_answer}" if public_answer else "answer unavailable"
                )
            candidate_parts.append(
                f"{role} via {method_name}: {answer_summary}"
            )
        add(
            "candidate_generation",
            (
                f"Generated {len(candidates)} public candidate summaries; "
                f"{len(viable)} remained viable. "
                + (f"Compared method families: {', '.join(methods)}." if methods else "")
                + (f" Candidate comparison: {'; '.join(candidate_parts)}." if candidate_parts else "")
            ),
        )

    reviews = by_name.get("peer_review_completed", [])
    rebuttals = by_name.get("rebuttal_completed", [])
    cross_phase = _last(by_name, "solver_peer_review_phase_completed")
    if reviews or rebuttals or cross_phase:
        challenged = sum(
            1 for item in reviews if item.get("challenged") is True
        )
        actions = list(
            dict.fromkeys(
                str(action)
                for item in rebuttals
                for action in (
                    item.get("actions", [])
                    if isinstance(item.get("actions", []), list)
                    else []
                )
                if str(action).strip()
            )
        )
        add(
            "cross_review",
            (
                f"Completed {len(reviews)} cross-review records and "
                f"{len(rebuttals)} rebuttal records; {challenged} reviews raised a challenge. "
                + (f"Public rebuttal actions: {', '.join(actions)}. " if actions else "")
                + "Candidate disagreements and "
                "criticisms were forwarded to verification and arbitration."
            ),
        )

    evidence = _last(by_name, "evidence_summary") or {}
    proof = _last(by_name, "proof_completion_summary") or {}
    verification_parts = [
        "Checked the selected candidate against public evidence and proof obligations."
    ]
    proof_status = str(proof.get("status", "")).strip()
    if proof_status:
        verification_parts.append(f"Proof-completion status: {proof_status}.")
    unresolved = proof.get("unresolved_obligation_ids", [])
    if isinstance(unresolved, list) and unresolved:
        verification_parts.append(
            f"Unresolved public obligations: {len(unresolved)}."
        )
    if evidence:
        selected_evidence = evidence.get("selected_candidate", {})
        if isinstance(selected_evidence, dict):
            verification_parts.append(
                "Selected-candidate checks: "
                + ", ".join(
                    f"{name}={int(selected_evidence.get(name, 0))}"
                    for name in ("pass", "fail", "unknown", "error")
                )
                + "."
            )
        verification_parts.append("Evidence results were included in the final decision.")
    add("verification", " ".join(verification_parts))

    repair = _last(by_name, "repair_history")
    if repair:
        attempts = repair.get("attempts", [])
        accepted = sum(
            1
            for item in attempts
            if isinstance(item, dict) and item.get("accepted") is True
        )
        add(
            "repair",
            f"Performed {len(attempts)} claim-local repair attempts; {accepted} were accepted after re-verification.",
        )

    selected_summary = next(
        (
            item
            for item in candidates
            if isinstance(item, dict) and item.get("selected") is True
        ),
        {},
    )
    arbitration = _last(by_name, "candidate_arbitrated") or {}
    selection_reason = str(
        arbitration.get(
            "selection_reason",
            selected_summary.get("selection_reason", ""),
        )
    ).strip()
    add(
        "arbitration",
        (
            "Applied evidence-gated deterministic arbitration to the viable candidates."
            + (f" Selection basis: {selection_reason}." if selection_reason else "")
        ),
    )

    activity = _last(by_name, "model_activity") or {}
    calls = activity.get("calls", [])
    if isinstance(calls, list) and calls:
        successful = sum(
            1
            for item in calls
            if isinstance(item, dict)
            and str(item.get("status", "")).casefold()
            in {"success", "completed", "ok"}
        )
        roles = list(
            dict.fromkeys(
                str(item.get("role", "")).strip()
                for item in calls
                if isinstance(item, dict) and str(item.get("role", "")).strip()
            )
        )
        add(
            "model_call",
            (
                f"Recorded {len(calls)} model calls, including {successful} successful calls. "
                + (f"Participating roles: {', '.join(roles)}." if roles else "")
            ),
        )

    diagnostics = _last(by_name, "diagnostics") or {}
    if diagnostics:
        diagnostic_fields = {
            key: diagnostics.get(key)
            for key in (
                "truncation_verdicts",
                "deadline_phase",
                "elapsed_seconds",
                "model_calls",
                "prompt_tokens_avg",
                "circuit_open",
                "salvage_used",
                "sanitizer_issues",
                "error_code",
            )
        }
        add(
            "diagnostics",
            json.dumps(
                diagnostic_fields,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )

    response_mode = str(process.get("response_mode", "answer_only"))
    terminal = _last(by_name, "run_completed") or {}
    outcome = str(terminal.get("outcome", "unknown"))
    if response_mode == "proof_full":
        format_summary = "Preserved the public proof steps in final_response."
    else:
        format_summary = "Reduced final_response to the canonical exact answer only."
    add(
        "finalize",
        f"{format_summary} JSON serialization and public-output checks completed; outcome: {outcome}.",
    )

    items = _bound(items, active_limits)
    if not items:
        items = minimal_official_trace()
    validate_official_trace(items, limits=active_limits)
    return items


def validate_official_trace(
    trace: list[dict[str, Any]],
    *,
    limits: Mapping[str, Any] | JudgeTraceLimits | None = None,
) -> None:
    active_limits = _limits(limits)
    errors: list[str] = []
    if not isinstance(trace, list) or not trace:
        raise OfficialTraceIntegrityError("official trace must be a non-empty list")
    for index, item in enumerate(trace):
        if not isinstance(item, dict) or set(item) != {"step", "content"}:
            errors.append(f"trace item {index} must contain only step and content")
            continue
        step = item.get("step")
        content = item.get("content")
        if not isinstance(step, str) or not _STEP_NAME.fullmatch(step):
            errors.append(f"trace item {index} has an invalid step")
        if not isinstance(content, str) or not content.strip():
            errors.append(f"trace item {index} has empty content")
        if len(json.dumps(item, ensure_ascii=False)) > active_limits.judge_trace_event_max_chars:
            errors.append(f"trace item {index} exceeds the event character limit")
    if len(trace) > active_limits.judge_trace_max_events:
        errors.append("official trace exceeds the event limit")
    if len(json.dumps(trace, ensure_ascii=False)) > active_limits.judge_trace_max_chars:
        errors.append("official trace exceeds the character limit")
    if trace and trace[0].get("step") != "plan":
        errors.append("official trace must start with plan")
    if trace and trace[-1].get("step") != "finalize":
        errors.append("official trace must end with finalize")
    if errors:
        raise OfficialTraceIntegrityError("; ".join(dict.fromkeys(errors)))


def minimal_official_trace(
    *,
    outcome: str = "fallback",
    error_code: str = "public_trace_unavailable",
) -> list[dict[str, str]]:
    return [
        {
            "step": "plan",
            "content": "当前没有可用的完整公开推理计划。",
        },
        {
            "step": "diagnostics",
            "content": json.dumps(
                {
                    "truncation_verdicts": {
                        "complete": 0,
                        "suspect": 0,
                        "truncated": 0,
                    },
                    "deadline_phase": "unknown",
                    "elapsed_seconds": 0.0,
                    "model_calls": 0,
                    "prompt_tokens_avg": 0,
                    "circuit_open": False,
                    "salvage_used": False,
                    "sanitizer_issues": ["public_trace_unavailable"],
                    "error_code": error_code,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        },
        {
            "step": "finalize",
            "content": (
                "已返回当前可用的最安全兜底答案；"
                f"结果：{outcome}；原因：{error_code}。"
            ),
        },
    ]


def is_official_trace(trace: list[Any]) -> bool:
    return bool(trace) and all(
        isinstance(item, dict) and set(item) == {"step", "content"}
        for item in trace
    )


def _events_by_name(trace: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in trace:
        if not isinstance(item, dict):
            continue
        name = str(item.get("event", ""))
        if name:
            grouped.setdefault(name, []).append(item)
    return grouped


def _last(
    by_name: dict[str, list[dict[str, Any]]],
    name: str,
) -> dict[str, Any] | None:
    values = by_name.get(name, [])
    return values[-1] if values else None


def _limits(
    value: Mapping[str, Any] | JudgeTraceLimits | None,
) -> JudgeTraceLimits:
    if isinstance(value, JudgeTraceLimits):
        return value
    return JudgeTraceLimits.from_mapping(value)


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(1, limit - 3)].rstrip() + "..."


def _bound(
    items: list[dict[str, str]],
    limits: JudgeTraceLimits,
) -> list[dict[str, str]]:
    resident = list(items)
    for step in _OPTIONAL_STEPS:
        if (
            len(resident) <= limits.judge_trace_max_events
            and len(json.dumps(resident, ensure_ascii=False))
            <= limits.judge_trace_max_chars
        ):
            break
        resident = [item for item in resident if item["step"] != step]
    if len(resident) > limits.judge_trace_max_events:
        resident = resident[: max(1, limits.judge_trace_max_events - 1)] + [
            resident[-1]
        ]
    if len(json.dumps(resident, ensure_ascii=False)) > limits.judge_trace_max_chars:
        per_item = max(128, limits.judge_trace_max_chars // max(1, len(resident)) - 96)
        resident = [
            {"step": item["step"], "content": _clip(item["content"], per_item)}
            for item in resident
        ]
    return resident
