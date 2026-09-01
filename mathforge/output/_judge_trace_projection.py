"""Judge Trace 的精简、可审计投影。

内部 trace 可以很大，但公开 trace 只保留数学过程、候选血缘、证据闭环和
诊断信号。所有裁剪与脱敏都在 Host 侧完成，绝不公开私有推理或原始响应。
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
import re
from typing import Any, Iterable, Mapping

from mathforge.harness.events import EVENT_STAGES
from mathforge.harness.trace import trace_accuracy_priority
from mathforge.output.deterministic_formatter import latex_final_answer
from mathforge.output.loop_health import build_closed_loop_health


JUDGE_TRACE_SCHEMA_VERSION = "4.0"
JUDGE_EVENT_STAGES = {
    **EVENT_STAGES,
    "solution_process": "solution",
    "workflow_overview": "workflow",
    "diagnostics": "diagnostics",
    "candidate_summaries": "candidate_generation",
    "evidence_summary": "evidence",
    "proof_completion_summary": "verification",
    "decision_summary": "arbitration",
    "model_activity": "model_activity",
    "repair_history": "repair",
    "trace_compaction": "finalization",
}
_ESSENTIAL_EVENTS = frozenset(
    {
        "solution_process",
        "workflow_overview",
        "session_started",
        "evidence_summary",
        "proof_completion_summary",
        "candidate_arbitrated",
        "final_answer_selected",
        "closed_loop_health",
        "budget_summary",
        "run_completed",
        "fallback_used",
        "deadline_finalize",
        "per_case_wall_clock_timeout",
        "case_execution_failed",
    }
)
_FORBIDDEN_KEYS = re.compile(
    r"^(?:raw_(?:response|completion|prompt)|candidate_text|solution_text|"
    r"chain[_-]?of[_-]?thought|scratchpad|hidden[_-]?reasoning|"
    r"private[_-]?reasoning|internal[_-]?prompt|traceback|exception|"
    r"api[_-]?key|authorization|credentials?)$",
    re.I,
)
_UNSAFE_VALUE = re.compile(
    r"(?:(?<![A-Za-z0-9_])[A-Za-z]:[\\/]|/(?:home|Users|root|tmp)/)|"
    r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}|"
    r"\bbearer\s+\S+|\btraceback\s*\(most recent call last\)",
    re.I,
)


class JudgeTraceIntegrityError(ValueError):
    """公开 Judge Trace 不满足 schema 或安全边界。"""


@dataclass(frozen=True)
class JudgeTraceLimits:
    final_response_max_chars: int = 20000
    public_result_max_bytes: int = 4000000
    judge_trace_max_events: int = 64
    judge_trace_max_chars: int = 196608
    judge_trace_event_max_chars: int = 16384
    candidate_summary_max_count: int = 8

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "JudgeTraceLimits":
        if payload is None:
            result = cls()
        else:
            result = cls(
                **{
                    name: int(payload.get(name, getattr(cls(), name)))
                    for name in cls.__dataclass_fields__
                }
            )
        result.validate()
        return result

    def validate(self) -> None:
        if not 4096 <= self.final_response_max_chars <= 200000:
            raise ValueError("final_response_max_chars is invalid")
        if self.public_result_max_bytes < 4096:
            raise ValueError("public_result_max_bytes is too small")
        if self.judge_trace_max_events < 8:
            raise ValueError("judge_trace_max_events is too small")
        if self.judge_trace_max_chars < 4096:
            raise ValueError("judge_trace_max_chars is too small")
        if not 1024 <= self.judge_trace_event_max_chars < self.judge_trace_max_chars:
            raise ValueError("judge_trace_event_max_chars is invalid")
        if not 1 <= self.candidate_summary_max_count <= 64:
            raise ValueError("candidate_summary_max_count is invalid")


def project_judge_trace(
    trace: list[dict[str, Any]],
    *,
    final_response: str,
    limits: Mapping[str, Any] | JudgeTraceLimits | None = None,
) -> list[dict[str, Any]]:
    """把内部事件压缩为稳定的 judge-facing trace。"""

    active = _limits(limits)
    grouped = _group(trace)
    selected = _selected_id(grouped)
    events: list[dict[str, Any]] = []
    elapsed = 0

    def add(name: str, source: Mapping[str, Any] | None, details: Mapping[str, Any] | None = None, *, at: int | None = None) -> None:
        nonlocal elapsed
        if source is None:
            return
        value = dict(details) if details is not None else _public(source)
        for key in ("event", "stage", "schema_version", "seq", "elapsed_ms"):
            value.pop(key, None)
        elapsed = max(elapsed, _n(at if at is not None else source.get("elapsed_ms", elapsed)))
        events.append(_bound_event({"schema_version": JUDGE_TRACE_SCHEMA_VERSION, "seq": len(events) + 1, "elapsed_ms": elapsed, "event": name, "stage": JUDGE_EVENT_STAGES[name], **value}, active))

    problem = _last(grouped, "problem_parsed")
    final = _last(grouped, "final_answer_selected")
    source = final or _last(grouped, "run_completed") or _last(grouped, "fallback_used") or _first(grouped, "session_started")
    public_solution = final.get("public_solution", {}) if final else {}
    if not isinstance(public_solution, dict):
        public_solution = {}
    add("solution_process", source, {"status": "complete" if selected else "unavailable", "response_mode": str((problem or {}).get("response_mode", "answer_only")), "candidate_id": selected, "method": _selected_method(grouped, selected), "steps": _steps(public_solution.get("public_solution_steps", []), active), "conclusion": _text(latex_final_answer(str(public_solution.get("final_answer", "")), str((problem or {}).get("answer_type", "text"))), max(256, active.judge_trace_event_max_chars // 4))}, at=0)
    add("workflow_overview", source, _workflow(grouped, selected), at=0)
    add("session_started", _first(grouped, "session_started"), _select(_first(grouped, "session_started"), ("session_id", "request_fingerprint", "config_profile", "config_schema_version", "config_hash", "prompt_hash", "skill_hash", "rag_hash", "tool_hash", "code_commit", "code_dirty", "requested_model", "request_source", "response_model_observable", "thinking_mode_observable", "provenance_hash")))
    add("problem_parsed", problem, _select(problem, ("problem_type", "answer_type", "response_mode", "answer_type_confidence", "target_phrase", "target_kind", "domain", "domains", "assumptions", "definitions", "quantifiers", "constraints", "ambiguities", "difficulty_features", "subproblem_hints", "parse_confidence", "parser_confidence")))
    obligations = _last(grouped, "problem_obligations_planned")
    add("problem_obligations_planned", obligations, {**_select(obligations, ("enabled", "timing")), "obligations": [_select(item, ("obligation_id", "kind", "description", "required", "origin")) for item in (obligations or {}).get("obligations", []) if isinstance(item, dict)]})
    route = _last(grouped, "route_planned")
    add("route_planned", route, _select(route, ("router_llm_attempted", "router_source", "router_fallback_reason", "protocol_parse_tier", "protocol_recovery_reason", "protocol_assurance_degradation", "plan_id", "plan_version", "parent_plan_id", "original_condition_digest", "subgoals", "task_proposals", "route_artifact_id", "plan_artifact_id", "plan_message_id", "primary_subject", "auxiliary_subject", "risk_level", "routing_confidence", "ambiguity_margin", "complexity_flags", "subject_candidates", "selected_skills", "selected_tools", "method_families", "routing_reasons")))
    state = _last(grouped, "reasoning_state_initialized")
    add("reasoning_state_initialized", state, _select(state, ("state_id", "state_version", "reasoning_state_schema_version", "problem_frame_digest", "preserved_invariants")))
    planned = _last(grouped, "autonomous_solver_planned")
    add("autonomous_solver_planned", planned, _select(planned, ("enabled", "governance", "remaining_calls", "remaining_seconds")))
    for name in ("round_summary", "tool_feedback_completed"):
        for item in grouped.get(name, []):
            add(name, item, _round_or_tool(item))
    reasoning = _last(grouped, "reasoning_loop_completed")
    add("reasoning_loop_completed", reasoning, _select(reasoning, ("state_id", "enabled", "completed_rounds", "action_turns", "progress_turns", "candidate_attempts", "candidate_synthesis_attempts", "abstained_agents", "stall_stops", "compact_recoveries", "proof_token_degradations", "agent_stop_reasons", "stop_reason", "degraded_reason", "candidate_id")))
    for name in ("llm_lemma_curator_completed", "lemma_request_completed", "agent_tool_request_completed", "agent_replan_completed", "candidate_partial_recovery_started", "candidate_stateful_rebuilt", "emergency_deferred", "recovery_corroboration", "verified_fact_promoted", "proof_backbone_updated", "proof_token_canary_degraded"):
        add(name, _last(grouped, name))
    add("skills_selected", _last(grouped, "skills_selected"), _skills(_last(grouped, "skills_selected")))
    budget = _last(grouped, "budget_summary")
    calls = _model_activity(grouped, budget)
    if calls:
        add("model_activity", budget, {"call_count": len(calls), "calls": calls})
    protocol = _last(grouped, "agent_protocol")
    if protocol:
        add("agent_protocol", protocol, _protocol(protocol))
    for name in ("agent_created", "task_assigned", "model_turn_started", "model_turn_completed", "artifact_published", "message_sent", "message_delivered", "message_consumed", "replan_acknowledged", "repair_committed", "repair_rolled_back", "agent_stopped"):
        add(name, _last(grouped, name))
    pool = _last(grouped, "candidate_pool_initialized")
    add("candidate_pool_initialized", pool, _select(pool, ("submitted_count", "independent_count", "structural_independence_gate", "candidate_isolation_released", "entries")))
    for name in ("peer_review_completed", "rebuttal_completed"):
        for item in grouped.get(name, []):
            add(name, item, _select(item, ("status", "review_id", "reviewer_role", "reviewer_agent_id", "author_agent_id", "candidate_id", "candidate_version", "finding_ids", "claim_ids", "challenged", "independent_model_call", "host_generated", "artifact_id", "message_id", "thread_id", "thread_status", "failure_code", "actions", "conceded_finding_ids")))
    phase = _last(grouped, "solver_peer_review_phase_completed")
    add("solver_peer_review_phase_completed", phase, _select(phase, ("status", "bidirectional_reviews", "rebuttals", "active_candidate_ids", "candidate_pool", "downstream_candidate_filter_applied")))
    case_event = _last(grouped, "case_trace_summary")
    case_summary = case_event.get("summary", {}) if case_event else {}
    candidate_rows, omitted = _candidate_summaries(grouped, case_summary, selected, active)
    if candidate_rows or omitted:
        payload: dict[str, Any] = {"candidates": candidate_rows}
        if omitted:
            payload["omitted"] = omitted
        add("candidate_summaries", case_event or _last(grouped, "candidate_generated"), payload)
    hard_gate = _last(grouped, "hard_evidence_gate")
    if hard_gate is not None or case_event is not None:
        evidence = case_summary.get("evidence", {}) if isinstance(case_summary, dict) else {}
        add("evidence_summary", hard_gate or case_event, {"selected_candidate_id": selected, "selected_candidate": _selected_evidence(case_summary, selected), "totals": _counts(evidence), "hard_gate_accepted": bool(selected and selected in _strings(hard_gate, "accepted")), "accepted_candidate_ids": _strings(hard_gate, "accepted"), "rejected_candidate_ids": _strings(hard_gate, "rejected")})
    for item in grouped.get("verifier_completed", []):
        add("verifier_completed", item, _select(item, ("used_llm", "finding_count", "reviewed_candidates", "reason", "status", "round", "review_targets", "reviewed_targets", "unreviewed_targets", "critique_id", "critique_artifact_id", "recommended_action", "peer_review_assessment_count", "independent_model_call")))
    for name in ("new_branch_started", "new_branch_completed", "final_audit_started", "final_audit_completed", "audit_reentry_decision", "verification_closure_recomputed", "decision_committed"):
        for item in grouped.get(name, []):
            add(name, item)
    repair = _repair_history(grouped, active)
    if repair:
        add("repair_history", repair[0], {"attempts": repair[1]})
    proof_gate = _last(grouped, "proof_completion_gate")
    graph = _last(grouped, "proof_graph_completed")
    proof = _proof_summary(proof_gate, graph, selected)
    status_final = _last(grouped, "proof_status_finalized")
    for item in (status_final or {}).get("statuses", []) if status_final else ():
        if isinstance(item, dict) and str(item.get("candidate_id", "")) == selected:
            proof.update(status=str(item.get("status", "incomplete")), final_reason_code=str(item.get("reason_code", "")))
    if proof_gate is not None or graph is not None:
        add("proof_completion_summary", proof_gate or graph, proof)
    add("proof_status_finalized", status_final, _select(status_final, ("statuses", "allowed_statuses")))
    arbitration = _last(grouped, "candidate_arbitrated")
    if arbitration is not None:
        ranks = arbitration.get("rank_details", []); selected_rank = next((item for item in ranks if isinstance(item, dict) and str(item.get("candidate_id", "")) == selected), {}) if isinstance(ranks, list) else {}
        add("candidate_arbitrated", arbitration, {"selected": selected, "viable_candidates": _strings(arbitration, "viable_candidates"), "rejected_candidates": _rejections(arbitration), "selection_reason": str(arbitration.get("selection_reason", "")), "tie_break_reason": str(arbitration.get("tie_break_reason", "")), "selected_verification_status": str(arbitration.get("selected_verification_status", "")), "selected_evidence_tier": str(selected_rank.get("evidence_tier", "")), "selected_review_support": _signed(selected_rank.get("review_support", 0)), "equivalence_cluster_count": len(arbitration.get("equivalence_clusters", [])) if isinstance(arbitration.get("equivalence_clusters", []), list) else 0, "used_llm_arbiter": bool(arbitration.get("used_llm_arbiter", False))})
    decision = _decision(grouped)
    if decision[0] is not None:
        add("decision_summary", decision[0], decision[1])
    if final is not None:
        add("final_answer_selected", final, {"candidate_id": selected, "selection_reason": str(final.get("selection_reason", "")), "public_solution": {"solution_process_ref": "trace[0]", "final_answer": _text(str(public_solution.get("final_answer", "")), max(256, active.judge_trace_event_max_chars // 4))}, "final_response_digest": sha256(str(final_response).encode("utf-8")).hexdigest(), "answer_validation": _safe(final.get("answer_validation", {}))})
    for name in ("fallback_used", "deadline_finalize", "per_case_wall_clock_timeout", "case_execution_failed"):
        item = _last(grouped, name); add(name, item, _select(item, ("reason", "error_code", "failed_phase", "checkpoint", "disabled", "elapsed_seconds", "wall_clock_seconds", "serialization_reserve_seconds", "final_phase")))
    formal = _last(grouped, "formal_entry_compatibility")
    add("formal_entry_compatibility", formal, _select(formal, ("public_contract", "immutable_files", "status_field_owner", "harness_status_limitation")))
    completed = _last(grouped, "run_completed"); health = _last(grouped, "closed_loop_health")
    health_details = _select(health, ("health", "model_dispatch", "candidate_flow", "verification_flow", "closure")) if health else build_closed_loop_health(trace, budget=budget, selected_candidate_id=selected, outcome=str((completed or {}).get("outcome", "")), error_code=str((completed or {}).get("error_code", "")))
    add("closed_loop_health", health or completed or budget, health_details)
    add("diagnostics", budget or completed or _first(grouped, "session_started"), _diagnostics(grouped, budget, completed))
    add("budget_summary", budget, _budget(budget))
    add("run_completed", completed, _select(completed, ("outcome", "error_code", "final_phase")))
    result = _bound_trace(events, active)
    validate_judge_trace(result, final_response=final_response, limits=active)
    return result


def validate_judge_trace(trace: list[dict[str, Any]], *, final_response: str, limits: Mapping[str, Any] | JudgeTraceLimits | None = None) -> None:
    active = _limits(limits); errors: list[str] = []
    if not isinstance(trace, list) or not trace: raise JudgeTraceIntegrityError("Judge Trace must not be empty")
    if len(trace) > active.judge_trace_max_events or _chars(trace) > active.judge_trace_max_chars: errors.append("Judge Trace budget exceeded")
    grouped: dict[str, list[dict[str, Any]]] = {}; elapsed: list[int] = []
    for index, event in enumerate(trace, 1):
        if not isinstance(event, dict): errors.append(f"event {index} is not an object"); continue
        name = str(event.get("event", "")); grouped.setdefault(name, []).append(event)
        if event.get("schema_version") != JUDGE_TRACE_SCHEMA_VERSION or event.get("seq") != index: errors.append(f"event {index} schema or sequence is invalid")
        value = event.get("elapsed_ms")
        if type(value) is not int or value < 0: errors.append(f"event {index} elapsed time is invalid")
        else: elapsed.append(value)
        if name not in JUDGE_EVENT_STAGES or event.get("stage") != JUDGE_EVENT_STAGES.get(name): errors.append(f"event {index} stage is invalid")
        if _chars(event) > active.judge_trace_event_max_chars or _unsafe(event): errors.append(f"event {index} exceeds public safety bounds")
        try: json.dumps(event, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError): errors.append(f"event {index} is not JSON serializable")
    if elapsed != sorted(elapsed): errors.append("Judge Trace elapsed time is not monotonic")
    if trace[0].get("event") != "solution_process": errors.append("solution_process must be first")
    if len(trace) < 2 or trace[1].get("event") != "workflow_overview": errors.append("workflow_overview must follow solution_process")
    if trace[-1].get("event") != "run_completed": errors.append("run_completed must be final")
    for name in ("solution_process", "workflow_overview", "session_started", "closed_loop_health", "budget_summary", "run_completed"):
        if len(grouped.get(name, [])) != 1: errors.append(f"{name} must occur exactly once")
    outcome = grouped.get("run_completed", [{}])[-1].get("outcome")
    if outcome == "primary":
        for name in ("evidence_summary", "proof_completion_summary", "candidate_arbitrated", "final_answer_selected"):
            if len(grouped.get(name, [])) != 1: errors.append(f"primary trace requires {name}")
    elif outcome in {"fallback", "timeout", "failed", "error"} and not any(grouped.get(name) for name in ("fallback_used", "deadline_finalize", "per_case_wall_clock_timeout", "case_execution_failed")): errors.append("terminal trace lacks failure category")
    process = grouped.get("solution_process", [{}])[-1]; selected = str(grouped.get("final_answer_selected", [{}])[-1].get("candidate_id", ""))
    if outcome == "primary" and (process.get("status") != "complete" or str(process.get("candidate_id", "")) != selected or not isinstance(process.get("steps"), list) or not process.get("steps") or not process.get("conclusion")): errors.append("primary solution process is incomplete")
    if grouped.get("final_answer_selected"):
        selected_event = grouped["final_answer_selected"][-1]; solution = selected_event.get("public_solution")
        if not isinstance(solution, dict) or "final_response" in solution: errors.append("selected public solution is invalid")
        if selected_event.get("final_response_digest") != sha256(str(final_response).encode("utf-8")).hexdigest(): errors.append("final response digest is inconsistent")
    expected = {"candidate_id", "role", "method_family", "status", "content_digest", "rejection_category", "evidence_summary", "public_final_answer", "public_solution_steps", "proof_status", "selection_reason", "selected", "solution_process_ref"}
    for event in grouped.get("candidate_summaries", []):
        candidates = event.get("candidates")
        if not isinstance(candidates, list) or len(candidates) > active.candidate_summary_max_count: errors.append("candidate summaries are invalid"); continue
        for candidate in candidates:
            if not isinstance(candidate, dict) or set(candidate) != expected: errors.append("candidate summary schema is invalid"); continue
            chosen = str(candidate.get("candidate_id", "")) == selected
            if bool(candidate.get("selected")) != chosen: errors.append("candidate selected marker is inconsistent")
            if chosen and candidate.get("solution_process_ref") != "trace[0]": errors.append("selected candidate lacks solution reference")
    for event in grouped.get("model_activity", []):
        calls = event.get("calls")
        if not isinstance(calls, list) or event.get("call_count") != len(calls): errors.append("model activity is invalid"); continue
        if [item.get("call_index") for item in calls if isinstance(item, dict)] != list(range(1, len(calls) + 1)): errors.append("model activity indexes are not contiguous")
        for item in calls:
            if not isinstance(item, dict) or not isinstance(item.get("candidate_ids"), list) or not str(item.get("role", "")) or not str(item.get("purpose", "")): errors.append("model activity attribution is incomplete")
    for event in grouped.get("repair_history", []):
        attempts = event.get("attempts")
        if not isinstance(attempts, list) or not attempts: errors.append("repair history is invalid")
        for item in attempts or []:
            if isinstance(item, dict) and item.get("accepted") is True and item.get("rolled_back") is True: errors.append("accepted repair cannot be rolled back")
    overview = grouped.get("workflow_overview", [{}])[-1]; steps = overview.get("steps")
    if not isinstance(steps, list) or not steps or overview.get("selected_candidate_id") != selected: errors.append("workflow overview is invalid")
    for index, step in enumerate(steps or [], 1):
        if not isinstance(step, dict) or step.get("step_index") != index or not str(step.get("phase", "")) or not str(step.get("outcome", "")) or not str(step.get("summary", "")) or not isinstance(step.get("related_events"), list): errors.append("workflow overview step is invalid")
    health = grouped.get("closed_loop_health", [{}])[-1]
    if not {"health", "model_dispatch", "candidate_flow", "verification_flow", "closure"} <= set(health): errors.append("closed-loop health schema is incomplete")
    if not isinstance(final_response, str) or not final_response.strip(): errors.append("final_response must be non-empty")
    if errors: raise JudgeTraceIntegrityError("; ".join(dict.fromkeys(errors)))


def minimal_judge_trace(*, outcome: str = "fallback", error_code: str = "all_candidates_failed") -> list[dict[str, Any]]:
    zero = {level: 0 for level in ("L1", "L2", "L3", "L4", "L5")}
    return _bound_trace([_event(1, "solution_process", status="unavailable", response_mode="answer_only", candidate_id="", method="", steps=[], conclusion=""), _event(2, "workflow_overview", outcome=outcome, selected_candidate_id="", steps=[{"step_index": 1, "phase": "fallback", "outcome": "used", "summary": error_code, "related_events": ["fallback_used"]}]), _event(3, "session_started", request_source="official_client_injected"), _event(4, "fallback_used", reason=error_code, error_code=error_code, failed_phase="created"), _event(5, "closed_loop_health", health="failed", model_dispatch={"status": "not_started"}, candidate_flow={"selected_candidate_id": ""}, verification_flow={"proof_status": "not_available"}, closure={"answer_available": False, "proof_status": "not_available"}), _event(6, "diagnostics", truncation_verdicts={"complete": 0, "suspect": 0, "truncated": 0}, deadline_phase="unknown", elapsed_seconds=0.0, model_calls=0, prompt_tokens_avg=0, circuit_open=False, salvage_used=False, answer_source="L5", answer_source_counts=zero, sanitizer_issues=[], error_code=error_code), _event(7, "budget_summary", outcome=outcome, answer_source="L5", answer_source_counts=zero), _event(8, "run_completed", outcome=outcome, error_code=error_code, final_phase="fallback_completed")], JudgeTraceLimits())


def _group(trace: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for event in trace:
        if isinstance(event, Mapping): result.setdefault(str(event.get("event", "")), []).append(dict(event))
    return result


def _first(grouped: Mapping[str, list[dict[str, Any]]], name: str) -> dict[str, Any] | None:
    values = grouped.get(name, []); return values[0] if values else None


def _last(grouped: Mapping[str, list[dict[str, Any]]], name: str) -> dict[str, Any] | None:
    values = grouped.get(name, []); return values[-1] if values else None


def _select(value: Mapping[str, Any] | None, fields: Iterable[str]) -> dict[str, Any]:
    return {field: value[field] for field in fields if value is not None and field in value}


def _public(value: Any, limit: int = 4096) -> Any:
    if value is None or isinstance(value, (bool, int)): return value
    if isinstance(value, float): return value if math.isfinite(value) else str(value)
    if isinstance(value, str): return _text(value, limit)
    if isinstance(value, Mapping): return {str(k): _public(v, limit) for k, v in value.items() if not _FORBIDDEN_KEYS.search(str(k))}
    if isinstance(value, (list, tuple)):
        items = [_public(item, limit) for item in value[:64]]
        return items if len(value) <= 64 else {"kind": "collection_summary", "items": items[:8], "item_count": len(value), "content_digest": _digest(value)}
    return f"[{type(value).__name__}]"


def _text(value: str, limit: int) -> str | dict[str, Any]:
    if len(value) <= limit: return value
    return {"kind": "text_summary", "chars": len(value), "content_digest": sha256(value.encode("utf-8")).hexdigest(), "preview": value[: min(512, max(0, limit // 4))]}


def _safe(value: Any) -> dict[str, Any]:
    result = _public(value)
    return result if isinstance(result, dict) else {}


def _digest(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _chars(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), default=str))


def _n(value: Any) -> int:
    try: return max(0, int(value)) if not isinstance(value, bool) else 0
    except (TypeError, ValueError): return 0


def _f(value: Any) -> float:
    try: return max(0.0, float(value)) if math.isfinite(float(value)) else 0.0
    except (TypeError, ValueError): return 0.0


def _signed(value: Any) -> int:
    try: return int(value) if not isinstance(value, bool) else 0
    except (TypeError, ValueError): return 0


def _strings(value: Mapping[str, Any] | None, key: str) -> list[str]:
    raw = value.get(key, []) if value else []
    return [str(item) for item in raw] if isinstance(raw, list) else []


def _counts(value: Any) -> dict[str, int]:
    source = value if isinstance(value, Mapping) else {}
    return {name: _n(source.get(name, 0)) for name in ("pass", "fail", "unknown", "error")}


def _steps(value: Any, limits: JudgeTraceLimits, *, item_limit: int | None = None) -> list[Any]:
    if not isinstance(value, list): return []
    limit = item_limit or min(32, max(1, limits.judge_trace_event_max_chars // 512))
    result = [_text(str(item), max(96, limits.judge_trace_event_max_chars // 6)) for item in value[:limit]]
    if len(value) > limit: result.append({"kind": "step_overflow", "item_count": len(value), "content_digest": _digest(value)})
    return result


def _selected_id(grouped: Mapping[str, list[dict[str, Any]]]) -> str:
    arbitration = _last(grouped, "candidate_arbitrated")
    if arbitration and arbitration.get("selected"): return str(arbitration["selected"])
    final = _last(grouped, "final_answer_selected")
    return str(final.get("candidate_id", "")) if final else ""


def _selected_method(grouped: Mapping[str, list[dict[str, Any]]], selected: str) -> str:
    for item in reversed(grouped.get("candidate_generated", [])):
        if str(item.get("candidate_id", "")) == selected: return str(item.get("method") or item.get("planned_method_family") or "")
    return ""


def _workflow(grouped: Mapping[str, list[dict[str, Any]]], selected: str) -> dict[str, Any]:
    problem = _last(grouped, "problem_parsed") or {}; route = _last(grouped, "route_planned") or {}
    generated = {str(item.get("candidate_id")) for item in grouped.get("candidate_generated", []) if item.get("candidate_id")}; failed = {str(item.get("candidate_id")) for item in grouped.get("candidate_generation_failed", []) if item.get("candidate_id")}; gate = _last(grouped, "hard_evidence_gate") or {}; verifier = _last(grouped, "verifier_completed") or {}; accepted = _strings(gate, "accepted"); rejected = _strings(gate, "rejected")
    steps = [("problem_understanding", "completed" if problem else "unavailable", f"已解析题目类型 {problem.get('problem_type', 'unknown')}，响应模式为 {problem.get('response_mode', 'answer_only')}。", ["problem_parsed"]), ("planning", "completed" if route else "deterministic_default", f"已选择数学领域 {route.get('primary_subject', problem.get('domain', 'unknown'))} 的推理路线。", ["route_planned", "skills_selected"]), ("candidate_generation", "completed" if generated else "failed", f"生成 {len(generated)} 个候选；{len(failed)} 次候选尝试失败。", ["model_activity", "candidate_summaries"]), ("verification", "accepted" if selected and selected in accepted else ("completed" if gate or verifier else "not_requested"), f"证据门接受 {len(accepted)} 个候选、拒绝 {len(rejected)} 个；验证器状态为 {verifier.get('status', 'not_used')}。", ["evidence_summary", "verifier_completed", "proof_completion_summary"]), ("arbitration", "selected" if selected else "no_selection", f"已选择候选 {selected}。" if selected else "没有候选通过最终仲裁。", ["candidate_arbitrated"])]
    outcome = str((_last(grouped, "run_completed") or {}).get("outcome", "fallback")); steps.append(("finalization", outcome, "已格式化选中候选。" if selected else "已返回确定性兜底答案。", ["final_answer_selected" if selected else "fallback_used"]))
    return {"outcome": outcome, "selected_candidate_id": selected, "steps": [{"step_index": i, "phase": a, "outcome": b, "summary": c, "related_events": d} for i, (a, b, c, d) in enumerate(steps, 1)]}


def _round_or_tool(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = ("state_id", "state_version", "round_index", "mode", "added_subgoal_ids", "updated_subgoal_ids", "closed_subgoal_ids", "added_claim_ids", "claim_dependency_refs", "evidence_ids", "opened_obligation_ids", "closed_obligation_ids", "information_gain", "next_step", "stop_reason", "degraded_reason", "state_tokens", "state_counting_mode", "state_compressed", "omitted_rounds", "next_protocol", "constructible_count", "work_item_count", "constructibility_rate", "failure_codes", "strategy_changed")
    result = _select(value, fields)
    if value.get("event") == "tool_feedback_completed": result["results"] = [_select(item, ("work_item_id", "claim_id", "tool_name", "status", "strength", "summary", "result_digest", "impact", "reason_code")) for item in value.get("results", []) if isinstance(item, dict)]
    return result


def _skills(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if not value: return {}
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in value.get("skills", []):
        if not isinstance(item, dict): continue
        key = (str(item.get("name", "")), str(item.get("version", "")), str(item.get("reason", "")))
        if not key[0]: continue
        row = grouped.setdefault(key, {"name": key[0], "version": key[1], "reason": key[2], "roles": [], "rank": _n(item.get("rank", 0)), "score": _n(item.get("score", 0))})
        row["roles"] = sorted(set(row["roles"]) | {str(role) for role in item.get("roles", [item.get("role", "")]) if role}); row["rank"] = min(row["rank"], _n(item.get("rank", 0))); row["score"] = max(row["score"], _n(item.get("score", 0)))
    return {"skill_fingerprint": str(value.get("skill_fingerprint", "")), "selection_context": str(value.get("selection_context", "")), "skills": list(grouped.values())}


def _model_activity(grouped: Mapping[str, list[dict[str, Any]]], budget: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    records = budget.get("model_call_records", []) if budget else []
    if not isinstance(records, list): return []
    starts = grouped.get("candidate_generation_started", []); primary = [str(item.get("candidate_id")) for item in starts if item.get("role") == "PrimarySolver" and item.get("candidate_id")]; alternative = [str(item.get("candidate_id")) for item in starts if item.get("role") == "AlternativeSolver" and item.get("candidate_id")]; proposed = [str(item.get("proposed_candidate_id")) for item in grouped.get("repair_proposed", []) if item.get("proposed_candidate_id")]; verifier = _last(grouped, "verifier_completed") or {}; reviewed = _strings(verifier, "reviewed_candidates"); selected = _selected_id(grouped); stage_counts: dict[str, int] = {}; calls: list[dict[str, Any]] = []
    role_by_stage = {"router": "RouterPlanner", "primary": "PrimarySolver", "alternative": "AlternativeSolver", "lemma": "LemmaCurator", "verifier": "VerifierSkeptic", "repair": "RepairAgent", "finalizer": "LLMFinalizer"}; purpose_by_stage = {"router": "route_planning", "primary": "candidate_reasoning", "alternative": "alternative_candidate_reasoning", "lemma": "lemma_curation", "verifier": "candidate_cross_review", "repair": "claim_local_repair", "finalizer": "verified_exposition_finalization"}
    fields = ("call_id", "logical_call_index", "logical_call_consumed", "dispatched", "stage", "turn_kind", "agent_id", "task_id", "turn_id", "plan_id", "subgoal_ids", "planned_method_family", "output_artifact_id", "message_id", "agent_mode", "status", "failure_code", "response_validation", "protocol_parse_tier", "protocol_recovery_reason", "protocol_assurance_degradation", "candidate_parse_tier", "transport_attempts", "prompt_tokens", "available_input_tokens", "configured_output_tokens", "requested_max_output_tokens", "effective_output_tokens", "effective_max_output_tokens", "stage_output_cap_tokens", "max_output_tokens", "context_window_tokens", "safety_margin_tokens", "counting_mode", "observed_output_tokens", "output_chars", "queue_elapsed_seconds", "agent_wait_seconds", "scheduler_wait_seconds", "rate_wait_seconds", "stage_p95_seconds", "effective_queue_budget_seconds", "configured_stage_timeout_seconds", "stage_timeout_seconds", "minimum_start_window_seconds", "effective_minimum_start_window_seconds", "client_timeout_seconds", "effective_stage_timeout_seconds", "finish_reason", "truncation_status", "tail_state", "stop_reason", "execution_elapsed_seconds", "total_elapsed_seconds", "transport_attempt_reservation", "transport_attempt_observability")
    for index, record in enumerate(records, 1):
        if not isinstance(record, dict): continue
        stage = str(record.get("stage", "unknown")); offset = stage_counts.get(stage, 0); stage_counts[stage] = offset + 1; ids = primary[:1] if stage == "primary" else alternative[offset:offset + 1] if stage == "alternative" else proposed[offset:offset + 1] if stage == "repair" else reviewed if stage == "verifier" else [selected] if stage == "finalizer" and selected else []
        row = {key: record.get(key, 0 if key.endswith("tokens") or key.endswith("seconds") else "") for key in fields}; row.update(call_index=index, stage=stage, turn_kind=str(record.get("turn_kind", stage)), role=str(record.get("agent_role", "")) or role_by_stage.get(stage, "UnknownRole"), purpose=purpose_by_stage.get(stage, "model_work"), candidate_ids=ids)
        for key in fields:
            if key.endswith("tokens") or key.endswith("seconds") or key in {"logical_call_index", "transport_attempts", "output_chars", "available_input_tokens", "configured_output_tokens", "requested_max_output_tokens", "effective_output_tokens", "effective_max_output_tokens", "stage_output_cap_tokens", "max_output_tokens", "context_window_tokens", "safety_margin_tokens", "transport_attempt_reservation"}: row[key] = _f(row[key]) if key.endswith("seconds") else _n(row[key])
        calls.append(_public(row))
    return calls


def _protocol(value: Mapping[str, Any]) -> dict[str, Any]:
    result = _select(value, ("protocol_schema_version", "mode", "selection_authority", "counts", "call_turn_count_match", "communication_integrity"))
    for name, fields in (("tasks", ("task_id", "task_type", "assigned_agent_id", "status", "input_artifact_ids", "output_artifact_ids")), ("messages", ("message_id", "thread_id", "sender_agent_id", "recipient_agent_id", "message_type", "task_id", "artifact_ids", "reply_to_message_id")), ("message_consumptions", ("receipt_id", "message_id", "consumer_agent_id", "turn_id", "artifact_ids")), ("threads", ("thread_id", "participant_agent_ids", "message_ids", "status")), ("protocol_sequence", ("sequence", "event_type", "agent_id", "task_id", "turn_id", "artifact_id", "message_id", "plan_version"))): result[name] = [_select(item, fields) for item in value.get(name, []) if isinstance(item, dict)]
    return result


def _candidate_summaries(grouped: Mapping[str, list[dict[str, Any]]], summary: Any, selected: str, limits: JudgeTraceLimits) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    generated = {str(item.get("candidate_id")): item for item in grouped.get("candidate_generated", []) if item.get("candidate_id")}; starts = {str(item.get("candidate_id")): item for item in grouped.get("candidate_generation_started", []) if item.get("candidate_id")}; failed = {str(item.get("candidate_id")): item for item in grouped.get("candidate_generation_failed", []) if item.get("candidate_id")}; states = {str(item.get("candidate_id")): item for item in (summary.get("candidates", []) if isinstance(summary, dict) else []) if isinstance(item, dict) and item.get("candidate_id")}; final_states = _last(grouped, "candidate_final_states") or {}; states.update({str(item.get("candidate_id")): item for item in final_states.get("candidates", []) if isinstance(item, dict) and item.get("candidate_id")}); order = list(dict.fromkeys([selected, *starts, *generated, *failed, *states])); rows: list[dict[str, Any]] = []; overflow: list[dict[str, Any]] = []
    for candidate_id in order:
        if not candidate_id: continue
        candidate = generated.get(candidate_id, {}); start = starts.get(candidate_id, {}); failure = failed.get(candidate_id, {}); state = states.get(candidate_id, {}); content = candidate.get("content", {}) if isinstance(candidate.get("content", {}), dict) else {}; chosen = candidate_id == selected; reasons = state.get("reason_codes", []); rejection = str(reasons[0]) if isinstance(reasons, list) and reasons else str(failure.get("reason", "not_selected_by_arbitration")); row = {"candidate_id": candidate_id, "role": str(candidate.get("role") or start.get("role") or state.get("role") or "unknown"), "method_family": str(candidate.get("planned_method_family") or start.get("planned_method_family") or "unavailable"), "status": "selected" if chosen else str(state.get("status") or failure.get("status") or candidate.get("status") or "unknown"), "content_digest": str(candidate.get("content_digest") or _digest({"candidate_id": candidate_id, "status": failure.get("status", "unavailable")})), "rejection_category": "" if chosen else rejection, "evidence_summary": _counts(state.get("evidence", {})), "public_final_answer": "" if chosen else _text(str(content.get("final_answer", "")), max(128, limits.judge_trace_event_max_chars // max(2, limits.candidate_summary_max_count * 2))), "public_solution_steps": [] if chosen else _steps(content.get("public_solution_steps", []), limits, item_limit=4), "proof_status": _candidate_proof_status(state), "selection_reason": "selected_by_arbitration" if chosen else (rejection if state.get("status") == "viable_not_selected" else f"rejected:{rejection}"), "selected": chosen, "solution_process_ref": "trace[0]" if chosen else ""}; (rows if len(rows) < limits.candidate_summary_max_count else overflow).append(row)
    omitted = {"kind": "candidate_summary_overflow", "count": len(overflow), "content_digest": _digest(overflow)} if overflow else None; return rows, omitted


def _candidate_proof_status(state: Mapping[str, Any]) -> str:
    obligations = state.get("proof_obligations", []); required = [item for item in obligations if isinstance(item, dict) and item.get("required") is True] if isinstance(obligations, list) else []
    if not required: return "not_available"
    return "complete_hard" if all(item.get("status") == "satisfied" for item in required) else "incomplete"


def _selected_evidence(summary: Any, selected: str) -> dict[str, int]:
    for item in (summary.get("candidates", []) if isinstance(summary, dict) else []):
        if isinstance(item, dict) and str(item.get("candidate_id", "")) == selected: return _counts(item.get("evidence", {}))
    return _counts({})


def _rejections(value: Mapping[str, Any]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in value.get("rejected_candidates", []) if isinstance(value.get("rejected_candidates", []), list) else []:
        if isinstance(item, dict):
            candidate_id = str(item.get("candidate_id", "")); reasons = item.get("reason_codes", item.get("reasons", [])); category = str(reasons[0]) if isinstance(reasons, list) and reasons else str(item.get("reason", "rejected"))
        else: candidate_id, category = str(item), "rejected"
        if candidate_id: result.append({"candidate_id": candidate_id, "rejection_category": category})
    return result


def _repair_history(grouped: Mapping[str, list[dict[str, Any]]], limits: JudgeTraceLimits) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    completions = grouped.get("repair_completed", []); proposals = {str(item.get("proposed_candidate_id")): item for item in grouped.get("repair_proposed", []) if item.get("proposed_candidate_id")}; attempts: list[dict[str, Any]] = []
    for item in completions:
        proposal = proposals.get(str(item.get("proposed_candidate_id", "")), {}); attempt = _select(item, ("repair_id", "candidate_id", "proposed_candidate_id", "status", "accepted", "rolled_back", "reason", "claim_ids", "finding_ids", "reverified", "content_digest")); proposed_id = str(item.get("proposed_candidate_id", "")); rolled_back = bool(item.get("rolled_back", False)); attempt["accepted"] = bool(proposed_id) and not rolled_back; attempt["rolled_back"] = rolled_back; content = proposal.get("proposed_content", {})
        if isinstance(content, dict): attempt["public_solution_steps"] = _steps(content.get("public_solution_steps", []), limits, item_limit=4)
        attempts.append(attempt)
    return (completions[-1], attempts) if attempts else None


def _proof_summary(gate: Mapping[str, Any] | None, graph: Mapping[str, Any] | None, selected_candidate_id: str) -> dict[str, Any]:
    if not selected_candidate_id: return {"selected_candidate_id": "", "status": "not_available", "unresolved_obligation_ids": [], "failed_obligation_ids": [], "failed_claim_ids": [], "hard_satisfied_obligation_ids": [], "model_reviewed_obligation_ids": [], "evidence_tier": "incomplete", "graph_summary": {}, "mode": "", "verifier_reason": ""}
    decisions = gate.get("decisions", []) if gate else []; decision = next((item for item in decisions if isinstance(item, dict) and str(item.get("candidate_id", "")) == selected_candidate_id), {}) if isinstance(decisions, list) else {}; graph_summary = ((graph or {}).get("graph", {}) or {}).get("summary", {}) if graph else {}
    def strings(key: str) -> list[str]:
        raw = decision.get(key, []); return [str(item) for item in raw] if isinstance(raw, list) else []
    return {"selected_candidate_id": selected_candidate_id, "status": str(decision.get("status", "complete_hard" if _n(graph_summary.get("unresolved_required_obligations", 0)) == 0 else "incomplete")), "unresolved_obligation_ids": strings("unresolved_obligation_ids"), "failed_obligation_ids": strings("failed_obligation_ids"), "failed_claim_ids": strings("failed_claim_ids"), "hard_satisfied_obligation_ids": strings("hard_satisfied_obligation_ids"), "model_reviewed_obligation_ids": strings("model_reviewed_obligation_ids"), "evidence_tier": str(decision.get("evidence_tier", "incomplete")), "graph_summary": _safe(graph_summary), "mode": str(gate.get("mode", "")) if gate else "", "verifier_reason": str(gate.get("verifier_reason", "")) if gate else ""}


def _decision(grouped: Mapping[str, list[dict[str, Any]]]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    source = next((_last(grouped, name) for name in ("candidate_conflict_matrix", "adaptive_fanout_decided", "shadow_probe_completed", "frozen_lemma_cache") if _last(grouped, name) is not None), None)
    if source is None: return None, {}
    result: dict[str, Any] = {}; cache = _last(grouped, "frozen_lemma_cache")
    if cache is not None: result["cache"] = {"requested": bool(cache.get("requested")), "enabled": bool(cache.get("enabled")), "disabled_reason": str(cache.get("disabled_reason", "")), "record_count": _n(cache.get("record_count", 0)), "store_hash": str(cache.get("store_hash", "")), "hit_count": len(cache.get("hits", [])) if isinstance(cache.get("hits", []), list) else 0, "runtime_write_count": _n(cache.get("runtime_write_count", 0))}
    shadow = _last(grouped, "shadow_probe_completed")
    if shadow is not None: result["shadow"] = _select(shadow, ("enabled", "status", "capability", "normalized_input", "limitations", "elapsed_seconds", "model_calls_added"))
    fanout = _last(grouped, "adaptive_fanout_decided")
    if fanout is not None: result["adaptive_fanout"] = _select(fanout, ("requested_candidates", "admitted_candidates", "reason_codes", "budget"))
    conflict = _last(grouped, "candidate_conflict_matrix")
    if conflict is not None:
        matrix = conflict.get("matrix", {}) if isinstance(conflict.get("matrix", {}), dict) else {}; pairs = matrix.get("conflicts", []) if isinstance(matrix.get("conflicts", []), list) else []
        result["cross_review"] = {"candidate_ids": [str(item) for item in matrix.get("candidate_ids", [])] if isinstance(matrix.get("candidate_ids", []), list) else [], "pair_count": len(pairs), "answer_conflict_count": sum(isinstance(item, dict) and item.get("answer_conflict") is True for item in pairs), "assumption_conflict_count": sum(isinstance(item, dict) and item.get("assumption_conflict") is True for item in pairs), "obligation_conflict_count": sum(isinstance(item, dict) and item.get("obligation_conflict") is True for item in pairs), "critical_claim_conflict_count": sum(isinstance(item, dict) and item.get("critical_claim_conflict") is True for item in pairs)}
    return source, result


def _diagnostics(grouped: Mapping[str, list[dict[str, Any]]], budget: Mapping[str, Any] | None, completed: Mapping[str, Any] | None) -> dict[str, Any]:
    verdicts = {"complete": 0, "suspect": 0, "truncated": 0}
    for item in grouped.get("truncation_assessed", []):
        status = str(item.get("status", "")).upper(); verdicts["complete" if status == "COMPLETE" else "suspect" if status in {"PROBABLE_TRUNCATION", "UNKNOWN", "SUSPECT"} else "truncated"] += 1
    budget = budget or {}; completed = completed or {}; calls = _n(budget.get("model_calls", budget.get("used_calls", 0))); prompt = _n(budget.get("prompt_tokens", 0)); issues: list[str] = []
    for item in grouped.get("answer_validation_warning", []):
        codes = item.get("codes", []); issues.extend(str(code) for code in codes if isinstance(codes, list) and str(code).strip())
    selected = _last(grouped, "final_answer_selected") or {}; validation = selected.get("answer_validation", {})
    if isinstance(validation, dict):
        codes = validation.get("codes", []); issues.extend(str(code) for code in codes if isinstance(codes, list) and str(code).strip())
    raw = budget.get("answer_source_counts", {}); source_counts = {level: _n(raw.get(level, 0)) for level in ("L1", "L2", "L3", "L4", "L5")} if isinstance(raw, dict) else {level: 0 for level in ("L1", "L2", "L3", "L4", "L5")}
    return {"truncation_verdicts": verdicts, "deadline_phase": str(budget.get("deadline_phase", "unknown")), "elapsed_seconds": _f(budget.get("elapsed_seconds", 0)), "model_calls": calls, "prompt_tokens_avg": round(prompt / calls, 3) if calls else 0, "circuit_open": str(budget.get("provider_health_state", "")).casefold() == "circuit_open", "salvage_used": bool(grouped.get("candidate_salvaged") or grouped.get("answer_ladder_selected") or str(completed.get("error_code", "")) == "degraded_candidate_salvage"), "answer_source": str(budget.get("answer_source", "L5")), "answer_source_counts": source_counts, "sanitizer_issues": list(dict.fromkeys(issues)), "error_code": str(completed.get("error_code", "")) or None}


def _budget(value: Mapping[str, Any] | None) -> dict[str, Any]:
    fields = ("max_calls", "used_calls", "calls_used", "model_calls", "model_call_policy", "budget_phase", "soft_call_checkpoints", "speculative_exploration_cutoff", "closure_reserve_calls", "calls_remaining", "prompt_tokens", "requested_output_tokens", "observed_output_tokens", "output_chars", "model_queue_budget_seconds", "model_queue_wait_seconds", "model_execution_seconds", "model_call_elapsed_seconds", "model_call_timeout_count", "model_queue_timeout_count", "model_admission_rejection_count", "model_admission_rejection_reasons", "model_call_failure_count", "model_response_rejection_count", "provider_health_state", "provider_active_tails", "provider_peak_tails", "provider_scheduler_peak", "provider_rate_reserved_weight", "provider_rate_peak_weight", "provider_rate_wait_count", "provider_rate_admitted_weight", "provider_circuit_trips", "provider_fast_failures", "used_tool_calls", "used_evidence_records", "elapsed_seconds", "remaining_seconds", "deadline_phase", "outcome", "answer_source", "answer_source_counts")
    return _select(value, fields)


def _bound_event(event: dict[str, Any], limits: JudgeTraceLimits) -> dict[str, Any]:
    if _chars(event) <= limits.judge_trace_event_max_chars: return event
    header = {key: event[key] for key in ("schema_version", "seq", "elapsed_ms", "event", "stage") if key in event}
    for key in ("candidate_id", "selected", "selected_candidate_id", "outcome", "call_count"):
        if key in event and isinstance(event[key], (str, int, bool)): header[key] = event[key]
    header["payload_summary"] = {"kind": "event_payload_summary", "fields": sorted(key for key in event if key not in header), "original_chars": _chars(event), "content_digest": _digest(event)}
    return header


def _bound_trace(events: list[dict[str, Any]], limits: JudgeTraceLimits) -> list[dict[str, Any]]:
    resident = list(events); omitted: list[dict[str, Any]] = []
    def remove() -> bool:
        candidates = [(trace_accuracy_priority(item.get("event")), index) for index, item in enumerate(resident) if item.get("event") not in _ESSENTIAL_EVENTS]
        if not candidates: return False
        _, index = max(candidates, key=lambda pair: (pair[0], -pair[1])); omitted.append(resident.pop(index)); return True
    while len(resident) > limits.judge_trace_max_events and remove(): pass
    while _chars(resident) > limits.judge_trace_max_chars and remove(): pass
    if omitted and len(resident) < limits.judge_trace_max_events:
        compact = _bound_event({"schema_version": JUDGE_TRACE_SCHEMA_VERSION, "seq": 0, "elapsed_ms": max((_n(item.get("elapsed_ms")) for item in resident), default=0), "event": "trace_compaction", "stage": JUDGE_EVENT_STAGES["trace_compaction"], "omitted_event_count": len(omitted), "omitted_event_names": sorted(str(item.get("event", "")) for item in omitted), "content_digest": _digest(omitted)}, limits)
        index = next((i for i, item in enumerate(resident) if item.get("event") == "budget_summary"), max(0, len(resident) - 1)); resident.insert(index, compact)
    if len(resident) > limits.judge_trace_max_events or _chars(resident) > limits.judge_trace_max_chars: raise JudgeTraceIntegrityError("protected Judge Trace events exceed configured limits")
    previous = 0
    for index, item in enumerate(resident, 1): item["seq"] = index; previous = max(previous, _n(item.get("elapsed_ms"))); item["elapsed_ms"] = previous
    return resident


def _unsafe(value: Any) -> bool:
    if isinstance(value, Mapping): return any(_FORBIDDEN_KEYS.search(str(key)) or _unsafe(item) for key, item in value.items())
    if isinstance(value, (list, tuple)): return any(_unsafe(item) for item in value)
    return isinstance(value, str) and bool(_UNSAFE_VALUE.search(value))


def _event(sequence: int, name: str, **details: Any) -> dict[str, Any]:
    return {"schema_version": JUDGE_TRACE_SCHEMA_VERSION, "seq": sequence, "elapsed_ms": 0, "event": name, "stage": JUDGE_EVENT_STAGES[name], **details}


def _limits(value: Mapping[str, Any] | JudgeTraceLimits | None) -> JudgeTraceLimits:
    return value if isinstance(value, JudgeTraceLimits) else JudgeTraceLimits.from_mapping(value)


__all__ = ["JUDGE_EVENT_STAGES", "JUDGE_TRACE_SCHEMA_VERSION", "JudgeTraceIntegrityError", "JudgeTraceLimits", "minimal_judge_trace", "project_judge_trace", "validate_judge_trace", "_proof_summary"]
