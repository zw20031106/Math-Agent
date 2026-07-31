from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
import re
from typing import Any, Iterable, Mapping

from mathforge.output.loop_health import (
    build_closed_loop_health,
    minimal_closed_loop_health,
)
from mathforge.output.deterministic_formatter import latex_final_answer


JUDGE_TRACE_SCHEMA_VERSION = "3.6"
JUDGE_EVENT_STAGES = {
    "solution_process": "solution",
    "session_started": "session",
    "effective_config_snapshot": "session",
    "problem_parsed": "parsing",
    "problem_obligations_planned": "verification",
    "route_planned": "routing",
    "reasoning_state_initialized": "reasoning",
    "long_horizon_planned": "reasoning",
    "round_summary": "reasoning",
    "reasoning_loop_completed": "reasoning",
    "skills_selected": "skill_selection",
    "tool_feedback_completed": "evidence",
    "verifier_completed": "verification",
    "candidate_summaries": "candidate_generation",
    "evidence_summary": "evidence",
    "proof_completion_summary": "verification",
    "decision_summary": "arbitration",
    "candidate_arbitrated": "arbitration",
    "candidate_salvaged": "arbitration",
    "final_answer_selected": "finalization",
    "fallback_used": "fallback",
    "deadline_finalize": "deadline",
    "per_case_wall_clock_timeout": "deadline",
    "case_execution_failed": "completion",
    "closed_loop_health": "finalization",
    "budget_summary": "finalization",
    "trace_compaction": "finalization",
    "run_completed": "completion",
}
_PROTECTED_EVENTS = frozenset(
    {
        "solution_process",
        "session_started",
        "round_summary",
        "tool_feedback_completed",
        "evidence_summary",
        "proof_completion_summary",
        "decision_summary",
        "candidate_arbitrated",
        "candidate_salvaged",
        "final_answer_selected",
        "fallback_used",
        "deadline_finalize",
        "per_case_wall_clock_timeout",
        "case_execution_failed",
        "closed_loop_health",
        "budget_summary",
        "run_completed",
    }
)
_FORBIDDEN_KEYS = re.compile(
    r"^(?:"
    r"raw_(?:response|completion|prompt)|candidate_text|solution_text|"
    r"chain[_-]?of[_-]?thought|scratchpad|hidden[_-]?reasoning|"
    r"private[_-]?reasoning|internal[_-]?prompt|traceback|exception|"
    r"api[_-]?key|authorization|credentials?"
    r")$",
    re.I,
)
_ABSOLUTE_PATH = re.compile(
    r"(?:(?<![A-Za-z0-9_])[A-Za-z]:[\\/]|/(?:home|Users|root|tmp)/)[^\s]+"
)
_API_TOKEN_VALUE = re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}")
_AUTHORIZATION_VALUE = re.compile(r"\bbearer\s+\S+", re.I)
_TRACEBACK_VALUE = re.compile(r"\btraceback\s*\(most recent call last\)", re.I)


class JudgeTraceIntegrityError(ValueError):
    pass


@dataclass(frozen=True)
class JudgeTraceLimits:
    final_response_max_chars: int = 20000
    public_result_max_bytes: int = 4000000
    judge_trace_max_events: int = 64
    judge_trace_max_chars: int = 196608
    judge_trace_event_max_chars: int = 16384
    candidate_summary_max_count: int = 8

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any] | None,
    ) -> JudgeTraceLimits:
        if payload is None:
            return cls()
        values = {
            field: int(payload.get(field, getattr(cls(), field)))
            for field in cls.__dataclass_fields__
        }
        limits = cls(**values)
        limits.validate()
        return limits

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
    active_limits = _limits(limits)
    by_name = _events_by_name(trace)
    selected_id = _selected_candidate_id(by_name)
    events: list[dict[str, Any]] = []
    last_elapsed = 0

    def append(
        name: str,
        source: dict[str, Any] | None,
        details: dict[str, Any],
        *,
        elapsed_override: int | None = None,
    ) -> None:
        nonlocal last_elapsed
        if source is None:
            return
        elapsed = (
            _nonnegative_int(elapsed_override)
            if elapsed_override is not None
            else _nonnegative_int(source.get("elapsed_ms", last_elapsed))
        )
        last_elapsed = max(last_elapsed, elapsed)
        event = {
            "schema_version": JUDGE_TRACE_SCHEMA_VERSION,
            "seq": len(events) + 1,
            "elapsed_ms": last_elapsed,
            "event": name,
            "stage": JUDGE_EVENT_STAGES[name],
            **details,
        }
        events.append(_bound_event(event, active_limits))

    session = _first(by_name, "session_started")
    problem = _last(by_name, "problem_parsed")
    final_event = _last(by_name, "final_answer_selected")
    public_solution = (
        final_event.get("public_solution", {})
        if isinstance(final_event, dict)
        else {}
    )
    if not isinstance(public_solution, dict):
        public_solution = {}
    solution_source = (
        final_event
        or _last(by_name, "run_completed")
        or _last(by_name, "fallback_used")
        or session
    )
    append(
        "solution_process",
        solution_source,
        {
            "status": "complete" if selected_id else "unavailable",
            "response_mode": str(
                problem.get("response_mode", "answer_only")
                if isinstance(problem, dict)
                else "answer_only"
            ),
            "candidate_id": selected_id,
            "method": _selected_candidate_method(by_name, selected_id),
            "steps": _selected_steps(
                public_solution.get("public_solution_steps", []),
                active_limits,
            ),
            "conclusion": _compact_text(
                latex_final_answer(
                    str(public_solution.get("final_answer", "")),
                    str(
                        problem.get("answer_type", "text")
                        if isinstance(problem, dict)
                        else "text"
                    ),
                ),
                max(256, active_limits.judge_trace_event_max_chars // 4),
            ),
        },
        elapsed_override=0,
    )
    append(
        "session_started",
        session,
        _select(
            session,
            (
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
            ),
        ),
    )
    append(
        "problem_parsed",
        problem,
        _select(
            problem,
            (
                "problem_type",
                "answer_type",
                "response_mode",
                "answer_type_confidence",
                "target_phrase",
                "target_kind",
                "domain",
                "assumptions",
                "definitions",
                "quantifiers",
                "constraints",
                "ambiguities",
                "difficulty_features",
                "subproblem_hints",
                "parse_confidence",
                "parser_confidence",
            ),
        ),
    )
    problem_obligations = _last(
        by_name,
        "problem_obligations_planned",
    )
    append(
        "problem_obligations_planned",
        problem_obligations,
        {
            **_select(
                problem_obligations,
                ("enabled", "timing"),
            ),
            "obligations": [
                _select(
                    item,
                    (
                        "obligation_id",
                        "kind",
                        "description",
                        "required",
                        "origin",
                    ),
                )
                for item in (
                    problem_obligations.get("obligations", [])
                    if isinstance(problem_obligations, dict)
                    else []
                )
                if isinstance(item, dict)
            ],
        },
    )
    route = _last(by_name, "route_planned")
    append(
        "route_planned",
        route,
        _select(
            route,
            (
                "primary_subject",
                "auxiliary_subject",
                "risk_level",
                "routing_confidence",
                "complexity_flags",
                "selected_skills",
                "selected_tools",
                "method_families",
                "routing_reasons",
            ),
        ),
    )
    state_initialized = _last(by_name, "reasoning_state_initialized")
    append(
        "reasoning_state_initialized",
        state_initialized,
        _select(
            state_initialized,
            (
                "state_id",
                "state_version",
                "reasoning_state_schema_version",
                "problem_frame_digest",
                "preserved_invariants",
            ),
        ),
    )
    long_horizon = _last(by_name, "long_horizon_planned")
    append(
        "long_horizon_planned",
        long_horizon,
        _select(
            long_horizon,
            (
                "enabled",
                "planned_rounds",
                "reason_code",
                "sequence_reserve_seconds",
                "remaining_calls",
                "remaining_seconds",
            ),
        ),
    )
    for round_event in by_name.get("round_summary", []):
        append(
            "round_summary",
            round_event,
            _select(
                round_event,
                (
                    "state_id",
                    "state_version",
                    "round_index",
                    "mode",
                    "added_subgoal_ids",
                    "updated_subgoal_ids",
                    "closed_subgoal_ids",
                    "added_claim_ids",
                    "claim_dependency_refs",
                    "evidence_ids",
                    "opened_obligation_ids",
                    "closed_obligation_ids",
                    "information_gain",
                    "next_step",
                    "stop_reason",
                    "degraded_reason",
                    "state_tokens",
                    "state_counting_mode",
                    "state_compressed",
                    "omitted_rounds",
                ),
            ),
        )
    for feedback_event in by_name.get("tool_feedback_completed", []):
        append(
            "tool_feedback_completed",
            feedback_event,
            {
                **_select(
                    feedback_event,
                    (
                        "state_id",
                        "state_version",
                        "round_index",
                        "next_protocol",
                        "constructible_count",
                        "work_item_count",
                        "constructibility_rate",
                        "failure_codes",
                        "strategy_changed",
                    ),
                ),
                "results": [
                    _select(
                        item,
                        (
                            "work_item_id",
                            "claim_id",
                            "tool_name",
                            "status",
                            "strength",
                            "summary",
                            "result_digest",
                            "impact",
                            "reason_code",
                        ),
                    )
                    for item in feedback_event.get("results", [])
                    if isinstance(item, dict)
                ],
            },
        )
    reasoning_completed = _last(by_name, "reasoning_loop_completed")
    append(
        "reasoning_loop_completed",
        reasoning_completed,
        _select(
            reasoning_completed,
            (
                "state_id",
                "enabled",
                "completed_rounds",
                "planned_rounds",
                "stop_reason",
                "degraded_reason",
                "candidate_id",
            ),
        ),
    )
    skills = _last(by_name, "skills_selected")
    append(
        "skills_selected",
        skills,
        _skill_summary(skills),
    )

    case_summary_event = _last(by_name, "case_trace_summary")
    case_summary = (
        case_summary_event.get("summary", {})
        if isinstance(case_summary_event, dict)
        else {}
    )
    candidate_summaries, omitted_candidates = _candidate_summaries(
        by_name,
        case_summary,
        selected_id=selected_id,
        limit=active_limits.candidate_summary_max_count,
        limits=active_limits,
    )
    if candidate_summaries or omitted_candidates:
        details: dict[str, Any] = {"candidates": candidate_summaries}
        if omitted_candidates:
            details["omitted"] = omitted_candidates
        append(
            "candidate_summaries",
            case_summary_event or _last(by_name, "candidate_generated"),
            details,
        )

    hard_gate = _last(by_name, "hard_evidence_gate")
    evidence_counts = (
        case_summary.get("evidence", {})
        if isinstance(case_summary, dict)
        else {}
    )
    selected_evidence = _selected_evidence_summary(case_summary, selected_id)
    if hard_gate is not None or case_summary_event is not None:
        append(
            "evidence_summary",
            hard_gate or case_summary_event,
            {
                "selected_candidate_id": selected_id,
                "selected_candidate": selected_evidence,
                "totals": _status_counts(evidence_counts),
                "hard_gate_accepted": bool(
                    selected_id
                    and selected_id in _string_list(hard_gate, "accepted")
                ),
                "accepted_candidate_ids": _string_list(hard_gate, "accepted"),
                "rejected_candidate_ids": _string_list(hard_gate, "rejected"),
            },
        )

    for verifier_event in by_name.get("verifier_completed", []):
        append(
            "verifier_completed",
            verifier_event,
            _select(
                verifier_event,
                (
                    "used_llm",
                    "finding_count",
                    "reviewed_candidates",
                    "reason",
                    "status",
                    "round",
                    "review_targets",
                    "reviewed_targets",
                    "unreviewed_targets",
                ),
            ),
        )

    proof_gate = _last(by_name, "proof_completion_gate")
    graph_event = _last(by_name, "proof_graph_completed")
    proof_details = _proof_summary(
        proof_gate,
        graph_event,
        selected_candidate_id=selected_id,
    )
    if proof_gate is not None or graph_event is not None:
        append(
            "proof_completion_summary",
            proof_gate or graph_event,
            proof_details,
        )

    arbitration = _last(by_name, "candidate_arbitrated")
    if arbitration is not None:
        rank_details = arbitration.get("rank_details", [])
        if not isinstance(rank_details, list):
            rank_details = []
        selected_rank = next(
            (
                item
                for item in rank_details
                if isinstance(item, dict)
                and str(item.get("candidate_id", "")) == selected_id
            ),
            {},
        )
        append(
            "candidate_arbitrated",
            arbitration,
            {
                "selected": selected_id,
                "viable_candidates": _string_list(
                    arbitration,
                    "viable_candidates",
                ),
                "rejected_candidates": _rejection_summaries(arbitration),
                "selection_reason": str(
                    arbitration.get("selection_reason", "")
                ),
                "tie_break_reason": str(
                    arbitration.get("tie_break_reason", "")
                ),
                "selected_verification_status": str(
                    arbitration.get(
                        "selected_verification_status",
                        "",
                    )
                ),
                "selected_evidence_tier": str(
                    selected_rank.get("evidence_tier", "")
                ),
                "selected_review_support": _signed_int(
                    selected_rank.get("review_support", 0)
                ),
                "equivalence_cluster_count": len(
                    arbitration.get("equivalence_clusters", [])
                    if isinstance(
                        arbitration.get("equivalence_clusters", []),
                        list,
                    )
                    else []
                ),
                "used_llm_arbiter": bool(
                    arbitration.get("used_llm_arbiter", False)
                ),
            },
        )

    if final_event is not None:
        append(
            "final_answer_selected",
            final_event,
            {
                "candidate_id": selected_id,
                "selection_reason": str(
                    final_event.get("selection_reason", "")
                ),
                "public_solution": {
                    "solution_process_ref": "trace[0]",
                    "final_answer": _compact_text(
                        str(public_solution.get("final_answer", "")),
                        max(256, active_limits.judge_trace_event_max_chars // 4),
                    ),
                },
                "final_response_digest": sha256(
                    final_response.encode("utf-8")
                ).hexdigest(),
                "answer_validation": _safe_mapping(
                    final_event.get("answer_validation", {})
                ),
            },
        )

    for terminal_name in (
        "fallback_used",
        "deadline_finalize",
        "per_case_wall_clock_timeout",
        "case_execution_failed",
    ):
        terminal_event = _last(by_name, terminal_name)
        if terminal_event is not None:
            append(
                terminal_name,
                terminal_event,
                _select(
                    terminal_event,
                    (
                        "reason",
                        "error_code",
                        "failed_phase",
                        "checkpoint",
                        "disabled",
                        "elapsed_seconds",
                        "wall_clock_seconds",
                        "serialization_reserve_seconds",
                        "final_phase",
                    ),
                ),
            )

    budget = _last(by_name, "budget_summary")
    decision_source, decision_details = _decision_summary(by_name)
    append(
        "decision_summary",
        decision_source,
        decision_details,
    )
    completed = _last(by_name, "run_completed")
    health = _last(by_name, "closed_loop_health")
    if health is None:
        health_details = build_closed_loop_health(
            trace,
            budget=budget,
            selected_candidate_id=selected_id,
            outcome=str(completed.get("outcome", "")) if completed else "",
            error_code=str(completed.get("error_code", "")) if completed else "",
        )
    else:
        health_details = _select(
            health,
            (
                "health",
                "model_dispatch",
                "candidate_flow",
                "verification_flow",
                "closure",
            ),
        )
    append(
        "closed_loop_health",
        health or completed or budget,
        health_details,
    )
    append(
        "budget_summary",
        budget,
        _budget_summary(budget),
    )
    append(
        "run_completed",
        completed,
        _select(
            completed,
            ("outcome", "error_code", "final_phase"),
        ),
    )

    events = _bound_trace(events, active_limits)
    validate_judge_trace(
        events,
        final_response=final_response,
        limits=active_limits,
    )
    return events


def validate_judge_trace(
    trace: list[dict[str, Any]],
    *,
    final_response: str,
    limits: Mapping[str, Any] | JudgeTraceLimits | None = None,
) -> None:
    active_limits = _limits(limits)
    errors: list[str] = []
    if not trace:
        raise JudgeTraceIntegrityError("Judge Trace must not be empty")
    if len(trace) > active_limits.judge_trace_max_events:
        errors.append("Judge Trace event budget exceeded")
    if _serialized_chars(trace) > active_limits.judge_trace_max_chars:
        errors.append("Judge Trace character budget exceeded")

    elapsed: list[int] = []
    by_name: dict[str, list[dict[str, Any]]] = {}
    for index, event in enumerate(trace, start=1):
        if not isinstance(event, dict):
            errors.append(f"event {index} is not an object")
            continue
        name = str(event.get("event", ""))
        by_name.setdefault(name, []).append(event)
        if event.get("schema_version") != JUDGE_TRACE_SCHEMA_VERSION:
            errors.append(f"event {index} Judge Trace schema is invalid")
        if event.get("seq") != index:
            errors.append(f"event {index} sequence is invalid")
        event_elapsed = event.get("elapsed_ms")
        if type(event_elapsed) is not int or event_elapsed < 0:
            errors.append(f"event {index} elapsed time is invalid")
        else:
            elapsed.append(event_elapsed)
        if name not in JUDGE_EVENT_STAGES:
            errors.append(f"event {index} is not judge-facing")
        elif event.get("stage") != JUDGE_EVENT_STAGES[name]:
            errors.append(f"event {index} stage is invalid")
        if _serialized_chars(event) > active_limits.judge_trace_event_max_chars:
            errors.append(f"event {index} character budget exceeded")
        if _contains_unsafe_content(event):
            errors.append(f"event {index} contains unsafe content")
        try:
            if json.loads(
                json.dumps(
                    event,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                )
            ) != event:
                errors.append(f"event {index} does not JSON round-trip")
        except (TypeError, ValueError):
            errors.append(f"event {index} is not JSON serializable")
    if elapsed != sorted(elapsed):
        errors.append("Judge Trace elapsed time is not monotonic")
    if trace[0].get("event") != "solution_process":
        errors.append("solution_process must be the first Judge Trace event")
    if trace[-1].get("event") != "run_completed":
        errors.append("run_completed must be the final Judge Trace event")
    for required in (
        "solution_process",
        "session_started",
        "closed_loop_health",
        "budget_summary",
        "run_completed",
    ):
        if len(by_name.get(required, [])) != 1:
            errors.append(f"{required} must occur exactly once")

    completed = by_name.get("run_completed", [{}])[-1]
    outcome = completed.get("outcome")
    if outcome == "primary":
        for required in (
            "evidence_summary",
            "proof_completion_summary",
            "candidate_arbitrated",
            "final_answer_selected",
        ):
            if len(by_name.get(required, [])) != 1:
                errors.append(f"primary Judge Trace requires {required}")
    elif outcome in {"fallback", "timeout"} and not any(
        by_name.get(name)
        for name in (
            "fallback_used",
            "deadline_finalize",
            "per_case_wall_clock_timeout",
        )
    ):
        errors.append("terminal Judge Trace lacks a safe failure category")

    selected_event = by_name.get("final_answer_selected", [{}])[-1]
    selected_id = str(selected_event.get("candidate_id", ""))
    process = by_name.get("solution_process", [{}])[-1]
    if outcome == "primary":
        if process.get("status") != "complete":
            errors.append("primary Judge Trace solution process is incomplete")
        if str(process.get("candidate_id", "")) != selected_id:
            errors.append("solution process candidate is inconsistent")
        if not isinstance(process.get("steps"), list) or not process.get("steps"):
            errors.append("primary Judge Trace lacks public solution steps")
        if not process.get("conclusion"):
            errors.append("primary Judge Trace lacks a public conclusion")
    if by_name.get("final_answer_selected"):
        solution = selected_event.get("public_solution")
        if not isinstance(solution, dict):
            errors.append("selected public solution is invalid")
        elif "final_response" in solution:
            errors.append("Judge Trace duplicates final_response")
        expected_digest = sha256(final_response.encode("utf-8")).hexdigest()
        if selected_event.get("final_response_digest") != expected_digest:
            errors.append("Judge Trace final response digest is inconsistent")
    for event in by_name.get("candidate_summaries", []):
        candidates = event.get("candidates")
        if not isinstance(candidates, list):
            errors.append("candidate summaries must be a list")
            continue
        if len(candidates) > active_limits.candidate_summary_max_count:
            errors.append("candidate summary count exceeded")
        expected = {
            "candidate_id",
            "role",
            "method_family",
            "status",
            "content_digest",
            "rejection_category",
            "evidence_summary",
            "public_final_answer",
            "public_solution_steps",
            "proof_status",
            "selection_reason",
        }
        for candidate in candidates:
            if not isinstance(candidate, dict) or set(candidate) != expected:
                errors.append("candidate summary schema is invalid")
                continue
            if str(candidate.get("candidate_id", "")) == selected_id:
                errors.append("selected candidate appears in rejected summaries")
            if candidate.get("status") != "viable_not_selected" and (
                candidate.get("public_final_answer")
                or candidate.get("public_solution_steps")
            ):
                errors.append("rejected candidate exposes public answer content")

    _validate_closed_loop_health(by_name, outcome, selected_id, errors)

    if not isinstance(final_response, str) or not final_response.strip():
        errors.append("final_response must be a non-empty string")
    if errors:
        raise JudgeTraceIntegrityError("; ".join(dict.fromkeys(errors)))


def minimal_judge_trace(
    *,
    outcome: str = "fallback",
    error_code: str = "all_candidates_failed",
) -> list[dict[str, Any]]:
    events = [
        _judge_event(
            1,
            "solution_process",
            status="unavailable",
            response_mode="answer_only",
            candidate_id="",
            method="",
            steps=[],
            conclusion="",
        ),
        _judge_event(
            2,
            "session_started",
            request_source="official_client_injected",
        ),
        _judge_event(
            3,
            "fallback_used",
            reason=error_code,
            error_code=error_code,
            failed_phase="created",
        ),
        _judge_event(
            4,
            "closed_loop_health",
            **minimal_closed_loop_health(
                health="timeout" if outcome == "timeout" else "failed",
                root_failure_code=error_code,
            ),
        ),
        _judge_event(5, "budget_summary", outcome=outcome),
        _judge_event(
            6,
            "run_completed",
            outcome=outcome,
            error_code=error_code,
            final_phase="fallback_completed",
        ),
    ]
    return events


def _candidate_summaries(
    by_name: dict[str, list[dict[str, Any]]],
    case_summary: Any,
    *,
    selected_id: str,
    limit: int,
    limits: JudgeTraceLimits,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    starts = {
        str(event.get("candidate_id", "")): event
        for event in by_name.get("candidate_generation_started", [])
        if event.get("candidate_id")
    }
    generated = {
        str(event.get("candidate_id", "")): event
        for event in by_name.get("candidate_generated", [])
        if event.get("candidate_id")
    }
    failed = {
        str(event.get("candidate_id", "")): event
        for event in by_name.get("candidate_generation_failed", [])
        if event.get("candidate_id")
    }
    state_items = (
        case_summary.get("candidates", [])
        if isinstance(case_summary, dict)
        else []
    )
    summary_states = {
        str(item.get("candidate_id", "")): item
        for item in state_items
        if isinstance(item, dict) and item.get("candidate_id")
    }
    final_state_event = _last(by_name, "candidate_final_states")
    final_state_items = (
        final_state_event.get("candidates", [])
        if isinstance(final_state_event, dict)
        else []
    )
    final_states = {
        str(item.get("candidate_id", "")): item
        for item in final_state_items
        if isinstance(item, dict) and item.get("candidate_id")
    }
    states = {
        candidate_id: {
            **final_states.get(candidate_id, {}),
            **summary_states.get(candidate_id, {}),
        }
        for candidate_id in set(summary_states) | set(final_states)
    }
    order = list(dict.fromkeys([*starts, *generated, *failed, *states]))
    summaries: list[dict[str, Any]] = []
    omitted_source: list[dict[str, Any]] = []
    for candidate_id in order:
        if not candidate_id or candidate_id == selected_id:
            continue
        start = starts.get(candidate_id, {})
        candidate = generated.get(candidate_id, {})
        failure = failed.get(candidate_id, {})
        state = states.get(candidate_id, {})
        reason_codes = state.get("reason_codes", [])
        rejection = (
            str(reason_codes[0])
            if isinstance(reason_codes, list) and reason_codes
            else str(failure.get("reason", "not_selected_by_arbitration"))
        )
        viable = state.get("status") == "viable_not_selected"
        content = candidate.get("content", {})
        if not isinstance(content, dict):
            content = {}
        candidate_char_share = max(
            512,
            limits.judge_trace_event_max_chars // max(1, limit),
        )
        summary = {
            "candidate_id": candidate_id,
            "role": str(
                candidate.get("role")
                or start.get("role")
                or state.get("role")
                or "unknown"
            ),
            "method_family": str(
                candidate.get("planned_method_family")
                or start.get("planned_method_family")
                or "unavailable"
            ),
            "status": str(
                state.get("status")
                or failure.get("status")
                or candidate.get("status")
                or "unknown"
            ),
            "content_digest": str(
                candidate.get("content_digest")
                or _digest(
                    {
                        "candidate_id": candidate_id,
                        "status": failure.get("status", "unavailable"),
                    }
                )
            ),
            "rejection_category": rejection,
            "evidence_summary": _status_counts(
                state.get("evidence", {})
                if isinstance(state, dict)
                else {}
            ),
            "public_final_answer": (
                _compact_text(
                    str(content.get("final_answer", "")),
                    max(128, candidate_char_share // 4),
                )
                if viable
                else ""
            ),
            "public_solution_steps": (
                _candidate_steps(
                    content.get("public_solution_steps", []),
                    candidate_char_share,
                )
                if viable
                else []
            ),
            "proof_status": _candidate_proof_status(state),
            "selection_reason": (
                rejection if viable else f"rejected:{rejection}"
            ),
        }
        if len(summaries) < limit:
            summaries.append(summary)
        else:
            omitted_source.append(summary)
    omitted = None
    if omitted_source:
        omitted = {
            "kind": "candidate_summary_overflow",
            "count": len(omitted_source),
            "content_digest": _digest(omitted_source),
        }
    return summaries, omitted


def _proof_summary(
    proof_gate: dict[str, Any] | None,
    graph_event: dict[str, Any] | None,
    *,
    selected_candidate_id: str,
) -> dict[str, Any]:
    if not selected_candidate_id:
        return {
            "selected_candidate_id": "",
            "status": "not_available",
            "unresolved_obligation_ids": [],
            "failed_obligation_ids": [],
            "failed_claim_ids": [],
            "hard_satisfied_obligation_ids": [],
            "model_reviewed_obligation_ids": [],
            "evidence_tier": "incomplete",
            "graph_summary": {},
            "mode": "",
            "verifier_reason": "",
        }
    selected_decision: dict[str, Any] = {}
    if proof_gate is not None:
        decisions = proof_gate.get("decisions", [])
        if isinstance(decisions, list):
            selected_decision = next(
                (
                    item
                    for item in decisions
                    if isinstance(item, dict)
                    and str(item.get("candidate_id", ""))
                    == selected_candidate_id
                ),
                {},
            )
    graph = (
        graph_event.get("graph", {})
        if isinstance(graph_event, dict)
        else {}
    )
    graph_summary = (
        graph.get("summary", {})
        if isinstance(graph, dict)
        else {}
    )
    return {
        "selected_candidate_id": selected_candidate_id,
        "status": str(
            selected_decision.get(
                "status",
                "complete"
                if _nonnegative_int(
                    graph_summary.get("unresolved_required_obligations", 0)
                )
                == 0
                else "incomplete",
            )
        ),
        "unresolved_obligation_ids": _plain_string_list(
            selected_decision.get("unresolved_obligation_ids", [])
        ),
        "failed_obligation_ids": _plain_string_list(
            selected_decision.get("failed_obligation_ids", [])
        ),
        "failed_claim_ids": _plain_string_list(
            selected_decision.get("failed_claim_ids", [])
        ),
        "hard_satisfied_obligation_ids": _plain_string_list(
            selected_decision.get(
                "hard_satisfied_obligation_ids",
                [],
            )
        ),
        "model_reviewed_obligation_ids": _plain_string_list(
            selected_decision.get(
                "model_reviewed_obligation_ids",
                [],
            )
        ),
        "evidence_tier": str(
            selected_decision.get("evidence_tier", "incomplete")
        ),
        "graph_summary": _safe_mapping(graph_summary),
        "mode": str(proof_gate.get("mode", "")) if proof_gate else "",
        "verifier_reason": (
            str(proof_gate.get("verifier_reason", ""))
            if proof_gate
            else ""
        ),
    }


def _candidate_proof_status(state: dict[str, Any]) -> str:
    obligations = state.get("proof_obligations", [])
    if not isinstance(obligations, list):
        return "not_available"
    required = [
        item
        for item in obligations
        if isinstance(item, dict) and item.get("required") is True
    ]
    if not required:
        return "not_available"
    if all(item.get("status") == "reviewed" for item in required):
        return "model_reviewed"
    return (
        "complete"
        if all(item.get("status") == "satisfied" for item in required)
        else "incomplete"
    )


def _decision_summary(
    by_name: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    cache = _last(by_name, "frozen_lemma_cache")
    shadow = _last(by_name, "shadow_probe_completed")
    fanout = _last(by_name, "adaptive_fanout_decided")
    cross_review = _last(by_name, "candidate_conflict_matrix")
    source = cross_review or fanout or shadow or cache
    if source is None:
        return None, {}

    details: dict[str, Any] = {}
    if cache is not None:
        hits = cache.get("hits", [])
        if not isinstance(hits, list):
            hits = []
        details["cache"] = {
            "requested": bool(cache.get("requested", False)),
            "enabled": bool(cache.get("enabled", False)),
            "disabled_reason": str(cache.get("disabled_reason", "")),
            "record_count": _nonnegative_int(
                cache.get("record_count", 0)
            ),
            "store_hash": str(cache.get("store_hash", "")),
            "hit_count": len(hits),
            "hits": [
                _select(
                    hit,
                    (
                        "lemma_id",
                        "content_hash",
                        "score",
                        "assumption_checks",
                    ),
                )
                for hit in hits
                if isinstance(hit, dict)
            ],
            "runtime_write_count": _nonnegative_int(
                cache.get("runtime_write_count", 0)
            ),
        }
    if shadow is not None:
        details["shadow"] = _select(
            shadow,
            (
                "enabled",
                "status",
                "capability",
                "normalized_input",
                "limitations",
                "elapsed_seconds",
                "model_calls_added",
            ),
        )
    if fanout is not None:
        details["adaptive_fanout"] = _select(
            fanout,
            (
                "requested_candidates",
                "admitted_candidates",
                "reason_codes",
                "budget",
            ),
        )
    if cross_review is not None:
        matrix = cross_review.get("matrix", {})
        if not isinstance(matrix, dict):
            matrix = {}
        conflicts = matrix.get("conflicts", [])
        if not isinstance(conflicts, list):
            conflicts = []
        details["cross_review"] = {
            "candidate_ids": _plain_string_list(
                matrix.get("candidate_ids", [])
            ),
            "pair_count": len(conflicts),
            "answer_conflict_count": sum(
                isinstance(item, dict)
                and item.get("answer_conflict") is True
                for item in conflicts
            ),
            "assumption_conflict_count": sum(
                isinstance(item, dict)
                and item.get("assumption_conflict") is True
                for item in conflicts
            ),
            "obligation_conflict_count": sum(
                isinstance(item, dict)
                and item.get("obligation_conflict") is True
                for item in conflicts
            ),
            "critical_claim_conflict_count": sum(
                isinstance(item, dict)
                and item.get("critical_claim_conflict") is True
                for item in conflicts
            ),
        }
        verifier = _last(by_name, "verifier_completed")
        if verifier is not None:
            details["cross_review"].update(
                {
                    "review_target_count": len(
                        _plain_string_list(
                            verifier.get("review_targets", [])
                        )
                    ),
                    "reviewed_target_count": len(
                        _plain_string_list(
                            verifier.get("reviewed_targets", [])
                        )
                    ),
                    "unreviewed_target_count": len(
                        _plain_string_list(
                            verifier.get("unreviewed_targets", [])
                        )
                    ),
                    "review_status": str(
                        verifier.get("status", "unknown")
                    ),
                }
            )
    return source, details


def _validate_closed_loop_health(
    by_name: dict[str, list[dict[str, Any]]],
    outcome: Any,
    selected_id: str,
    errors: list[str],
) -> None:
    events = by_name.get("closed_loop_health", [])
    if len(events) != 1:
        return
    event = events[0]
    expected_fields = {
        "health",
        "model_dispatch",
        "candidate_flow",
        "verification_flow",
        "closure",
    }
    if not expected_fields <= set(event):
        errors.append("closed-loop health schema is incomplete")
        return
    health = str(event.get("health", ""))
    allowed = {
        "primary": {"healthy", "degraded"},
        "success": {"healthy", "degraded"},
        "fallback": {"failed"},
        "error": {"failed"},
        "failed": {"failed"},
        "timeout": {"timeout"},
        "interrupted": {"interrupted"},
    }
    if health not in allowed.get(str(outcome), {"failed"}):
        errors.append("closed-loop health conflicts with terminal outcome")

    candidate_flow = event.get("candidate_flow", {})
    closure = event.get("closure", {})
    if not isinstance(candidate_flow, dict) or not isinstance(closure, dict):
        errors.append("closed-loop health flow schema is invalid")
        return
    if str(candidate_flow.get("selected_candidate_id", "")) != selected_id:
        errors.append("closed-loop health selected candidate is inconsistent")
    if bool(closure.get("answer_available", False)) != bool(selected_id):
        errors.append("closed-loop health answer availability is inconsistent")

    proof_events = by_name.get("proof_completion_summary", [])
    expected_proof = "not_available"
    if proof_events and selected_id:
        status = str(proof_events[-1].get("status", "incomplete"))
        expected_proof = (
            status
            if status in {
                "complete",
                "model_reviewed",
                "incomplete",
                "failed",
            }
            else "incomplete"
        )
    if closure.get("proof_status") != expected_proof:
        errors.append("closed-loop health proof status is inconsistent")


def _budget_summary(event: dict[str, Any] | None) -> dict[str, Any]:
    fields = (
        "max_calls",
        "used_calls",
        "model_calls",
        "prompt_tokens",
        "requested_output_tokens",
        "observed_output_tokens",
        "output_chars",
        "model_queue_budget_seconds",
        "model_queue_wait_seconds",
        "model_execution_seconds",
        "model_call_elapsed_seconds",
        "model_call_timeout_count",
        "model_queue_timeout_count",
        "model_admission_rejection_count",
        "model_admission_rejection_reasons",
        "model_call_failure_count",
        "model_response_rejection_count",
        "provider_health_state",
        "provider_active_tails",
        "provider_peak_tails",
        "provider_scheduler_peak",
        "provider_circuit_trips",
        "provider_fast_failures",
        "used_tool_calls",
        "used_evidence_records",
        "elapsed_seconds",
        "remaining_seconds",
        "deadline_phase",
        "outcome",
    )
    result = _select(event, fields)
    records = event.get("model_call_records", []) if event else []
    if isinstance(records, list):
        result["model_calls"] = [
            _select(
                record,
                (
                    "stage",
                    "status",
                    "failure_code",
                    "response_validation",
                    "transport_attempts",
                    "queue_elapsed_seconds",
                    "stage_p95_seconds",
                    "effective_queue_budget_seconds",
                    "execution_elapsed_seconds",
                    "total_elapsed_seconds",
                    "prompt_tokens",
                    "available_input_tokens",
                    "configured_output_tokens",
                    "stage_output_cap_tokens",
                    "max_output_tokens",
                    "context_window_tokens",
                    "safety_margin_tokens",
                    "counting_mode",
                    "observed_output_tokens",
                    "output_chars",
                ),
            )
            for record in records
            if isinstance(record, dict)
        ]
    return result


def _skill_summary(event: dict[str, Any] | None) -> dict[str, Any]:
    if event is None:
        return {}
    grouped: dict[tuple[str, str, str], set[str]] = {}
    for skill in event.get("skills", []):
        if not isinstance(skill, dict):
            continue
        key = (
            str(skill.get("name", "")),
            str(skill.get("version", "")),
            str(skill.get("reason", "")),
        )
        roles = skill.get("roles", [skill.get("role", "")])
        if key[0] and isinstance(roles, list):
            grouped.setdefault(key, set()).update(
                str(role) for role in roles if role
            )
    result: dict[str, Any] = {
        "skill_fingerprint": str(event.get("skill_fingerprint", "")),
        "selection_context": str(event.get("selection_context", "")),
        "skills": [
            {
                "name": name,
                "version": version,
                "reason": reason,
                "roles": sorted(roles),
                "rank": min(
                    _nonnegative_int(item.get("rank", 0))
                    for item in event.get("skills", [])
                    if isinstance(item, dict)
                    and str(item.get("name", "")) == name
                    and str(item.get("version", "")) == version
                    and str(item.get("reason", "")) == reason
                ),
                "score": max(
                    _nonnegative_int(item.get("score", 0))
                    for item in event.get("skills", [])
                    if isinstance(item, dict)
                    and str(item.get("name", "")) == name
                    and str(item.get("version", "")) == version
                    and str(item.get("reason", "")) == reason
                ),
            }
            for (name, version, reason), roles in sorted(grouped.items())
        ],
    }
    return result


def _selected_evidence_summary(case_summary: Any, selected_id: str) -> dict[str, int]:
    candidates = (
        case_summary.get("candidates", [])
        if isinstance(case_summary, dict)
        else []
    )
    for candidate in candidates:
        if (
            isinstance(candidate, dict)
            and str(candidate.get("candidate_id", "")) == selected_id
        ):
            return _status_counts(candidate.get("evidence", {}))
    return _status_counts({})


def _rejection_summaries(event: dict[str, Any]) -> list[dict[str, str]]:
    values = event.get("rejected_candidates", [])
    if not isinstance(values, list):
        return []
    summaries: list[dict[str, str]] = []
    for value in values:
        if isinstance(value, dict):
            candidate_id = str(value.get("candidate_id", ""))
            reasons = value.get("reason_codes", value.get("reasons", []))
            category = (
                str(reasons[0])
                if isinstance(reasons, list) and reasons
                else str(value.get("reason", "rejected"))
            )
        else:
            candidate_id = str(value)
            category = "rejected"
        if candidate_id:
            summaries.append(
                {
                    "candidate_id": candidate_id,
                    "rejection_category": category,
                }
            )
    return summaries


def _selected_steps(value: Any, limits: JudgeTraceLimits) -> list[Any]:
    if not isinstance(value, list):
        return []
    text_limit = max(256, limits.judge_trace_event_max_chars // 6)
    item_limit = min(32, max(1, limits.judge_trace_event_max_chars // 512))
    steps = [
        _compact_text(str(step), text_limit)
        for step in value[:item_limit]
    ]
    if len(value) > item_limit:
        steps.append(
            {
                "kind": "step_overflow",
                "item_count": len(value),
                "content_digest": _digest(value),
            }
        )
    return steps


def _candidate_steps(value: Any, char_budget: int) -> list[Any]:
    if not isinstance(value, list):
        return []
    item_limit = min(4, max(1, char_budget // 512))
    text_limit = max(96, char_budget // max(2, item_limit * 2))
    steps = [
        _compact_text(str(step), text_limit)
        for step in value[:item_limit]
    ]
    if len(value) > item_limit:
        steps.append(
            {
                "kind": "step_overflow",
                "item_count": len(value),
                "content_digest": _digest(value),
            }
        )
    return steps


def _bound_event(
    event: dict[str, Any],
    limits: JudgeTraceLimits,
) -> dict[str, Any]:
    text_limit = max(256, limits.judge_trace_event_max_chars // 6)
    compacted = {
        key: (
            value
            if key in {
                "schema_version",
                "seq",
                "elapsed_ms",
                "event",
                "stage",
                "candidate_id",
                "selected",
                "selected_candidate_id",
            }
            else _compact_value(value, text_limit=text_limit)
        )
        for key, value in event.items()
    }
    if _serialized_chars(compacted) <= limits.judge_trace_event_max_chars:
        return compacted
    header = {
        key: compacted[key]
        for key in ("schema_version", "seq", "elapsed_ms", "event", "stage")
    }
    for key in ("candidate_id", "selected", "selected_candidate_id", "outcome"):
        if key in compacted and isinstance(compacted[key], (str, int, bool)):
            header[key] = compacted[key]
    header["payload_summary"] = {
        "kind": "event_payload_summary",
        "fields": sorted(
            key for key in event if key not in header
        ),
        "original_chars": _serialized_chars(event),
        "content_digest": _digest(event),
    }
    return header


def _bound_trace(
    events: list[dict[str, Any]],
    limits: JudgeTraceLimits,
) -> list[dict[str, Any]]:
    resident = list(events)
    omitted: list[dict[str, Any]] = []

    def remove_optional() -> bool:
        for index, event in enumerate(resident):
            if event.get("event") not in _PROTECTED_EVENTS:
                omitted.append(resident.pop(index))
                return True
        return False

    while len(resident) + (1 if omitted else 0) > limits.judge_trace_max_events:
        if not remove_optional():
            break
    while _serialized_chars(resident) > limits.judge_trace_max_chars:
        if not remove_optional():
            break
    if omitted:
        source_elapsed = max(
            (_nonnegative_int(event.get("elapsed_ms", 0)) for event in resident),
            default=0,
        )
        compaction = _bound_event(
            {
                "schema_version": JUDGE_TRACE_SCHEMA_VERSION,
                "seq": 0,
                "elapsed_ms": source_elapsed,
                "event": "trace_compaction",
                "stage": JUDGE_EVENT_STAGES["trace_compaction"],
                "omitted_event_count": len(omitted),
                "omitted_event_names": sorted(
                    str(event.get("event", "")) for event in omitted
                ),
                "content_digest": _digest(omitted),
            },
            limits,
        )
        insert_at = next(
            (
                index
                for index, event in enumerate(resident)
                if event.get("event") == "budget_summary"
            ),
            max(0, len(resident) - 1),
        )
        resident.insert(insert_at, compaction)
    if (
        len(resident) > limits.judge_trace_max_events
        or _serialized_chars(resident) > limits.judge_trace_max_chars
    ):
        raise JudgeTraceIntegrityError(
            "protected Judge Trace events exceed configured limits"
        )
    last_elapsed = 0
    for sequence, event in enumerate(resident, start=1):
        event["seq"] = sequence
        last_elapsed = max(
            last_elapsed,
            _nonnegative_int(event.get("elapsed_ms", 0)),
        )
        event["elapsed_ms"] = last_elapsed
    return resident


def _compact_value(value: Any, *, text_limit: int) -> Any:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, str):
        return _compact_text(value, text_limit)
    if isinstance(value, (list, tuple)):
        item_limit = 64
        items = [
            _compact_value(item, text_limit=text_limit)
            for item in value[:item_limit]
        ]
        if len(value) > item_limit:
            return {
                "kind": "collection_summary",
                "items": items[:8],
                "item_count": len(value),
                "content_digest": _digest(value),
            }
        return items
    if isinstance(value, dict):
        return {
            str(key): _compact_value(item, text_limit=text_limit)
            for key, item in value.items()
            if not _FORBIDDEN_KEYS.search(str(key))
        }
    return f"[{type(value).__name__}]"


def _compact_text(value: str, limit: int) -> str | dict[str, Any]:
    if len(value) <= limit:
        return value
    return {
        "kind": "text_summary",
        "chars": len(value),
        "content_digest": sha256(value.encode("utf-8")).hexdigest(),
        "preview": value[: min(256, max(0, limit // 4))],
    }


def _contains_unsafe_content(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if _FORBIDDEN_KEYS.search(str(key)) or _contains_unsafe_content(item):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_unsafe_content(item) for item in value)
    if isinstance(value, str):
        return bool(
            _ABSOLUTE_PATH.search(value)
            or _API_TOKEN_VALUE.search(value)
            or _AUTHORIZATION_VALUE.search(value)
            or _TRACEBACK_VALUE.search(value)
        )
    return False


def _selected_candidate_id(
    by_name: dict[str, list[dict[str, Any]]],
) -> str:
    arbitration = _last(by_name, "candidate_arbitrated")
    if arbitration is not None and arbitration.get("selected"):
        return str(arbitration["selected"])
    final_event = _last(by_name, "final_answer_selected")
    return str(final_event.get("candidate_id", "")) if final_event else ""


def _selected_candidate_method(
    by_name: dict[str, list[dict[str, Any]]],
    candidate_id: str,
) -> str:
    if not candidate_id:
        return ""
    for event in reversed(by_name.get("candidate_generated", [])):
        if str(event.get("candidate_id", "")) == candidate_id:
            return str(
                event.get("method")
                or event.get("planned_method_family")
                or ""
            )
    return ""


def _events_by_name(
    trace: Iterable[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for event in trace:
        if isinstance(event, dict):
            result.setdefault(str(event.get("event", "")), []).append(event)
    return result


def _first(
    by_name: dict[str, list[dict[str, Any]]],
    name: str,
) -> dict[str, Any] | None:
    values = by_name.get(name, [])
    return values[0] if values else None


def _last(
    by_name: dict[str, list[dict[str, Any]]],
    name: str,
) -> dict[str, Any] | None:
    values = by_name.get(name, [])
    return values[-1] if values else None


def _select(
    event: Mapping[str, Any] | None,
    fields: Iterable[str],
) -> dict[str, Any]:
    if event is None:
        return {}
    return {
        field: event[field]
        for field in fields
        if field in event
    }


def _string_list(
    event: Mapping[str, Any] | None,
    key: str,
) -> list[str]:
    if event is None:
        return []
    return _plain_string_list(event.get(key, []))


def _plain_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _status_counts(value: Any) -> dict[str, int]:
    source = value if isinstance(value, dict) else {}
    return {
        status: _nonnegative_int(source.get(status, 0))
        for status in ("pass", "fail", "unknown", "error")
    }


def _safe_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): item
        for key, item in value.items()
        if not _FORBIDDEN_KEYS.search(str(key))
    }


def _judge_event(sequence: int, name: str, **details: Any) -> dict[str, Any]:
    return {
        "schema_version": JUDGE_TRACE_SCHEMA_VERSION,
        "seq": sequence,
        "elapsed_ms": 0,
        "event": name,
        "stage": JUDGE_EVENT_STAGES[name],
        **details,
    }


def _limits(
    value: Mapping[str, Any] | JudgeTraceLimits | None,
) -> JudgeTraceLimits:
    if isinstance(value, JudgeTraceLimits):
        value.validate()
        return value
    return JudgeTraceLimits.from_mapping(value)


def _digest(value: Any) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return sha256(serialized.encode("utf-8")).hexdigest()


def _serialized_chars(value: Any) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    )


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _signed_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
