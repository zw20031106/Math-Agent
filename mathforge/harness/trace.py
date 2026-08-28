from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import math
import re
from threading import RLock
from time import monotonic
from typing import Any, Callable, Iterable

from mathforge.harness.events import (
    DEBUG_TRACE_SCHEMA_VERSION,
    EVENT_STAGES,
    JUDGE_EVENTS,
    PROTECTED_TRACE_EVENTS,
    TRACE_SCHEMA_VERSION,
)
from mathforge.harness.proof_graph import PROOF_GRAPH_SCHEMA_VERSION
from mathforge.harness.trace_summary import CASE_SUMMARY_SCHEMA_VERSION
from mathforge.harness.transport import SAFE_TRANSPORT_FAILURE_CODES


_SENSITIVE_KEYS = re.compile(
    r"^(?:"
    r"secret|.*[_-]secret|password|passwd|.*[_-]password|api[_-]?key|"
    r".*[_-]api[_-]?key|(?:access|auth|bearer|refresh|private|session|id)[_-]?token|"
    r"authorization|credentials?|exception|traceback|.*nonce"
    r")$",
    re.I,
)
_ABSOLUTE_PATH = re.compile(
    r"(?:(?<![A-Za-z0-9_])[A-Za-z]:[\\/]|/(?:home|Users|root|tmp)/)[^\s]+"
)
_API_TOKEN_VALUE = re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}")
_AUTHORIZATION_VALUE = re.compile(r"\b(?:authorization\s*:?\s*)?bearer\s+\S+", re.I)
_TRACEBACK_VALUE = re.compile(r"\btraceback\s*\(most recent call last\)", re.I)
_PRIVATE_REASONING_KEYS = re.compile(
    r"^(?:"
    r"candidate_text|raw_(?:response|completion|prompt)|"
    r"chain[_-]?of[_-]?thought|scratchpad|hidden[_-]?reasoning|"
    r"private[_-]?reasoning|internal[_-]?prompt"
    r")$",
    re.I,
)
_HARD_MAX_PUBLIC_EVENTS = 4096
_DEFAULT_INTERNAL_MAX_EVENTS = 4096
_LARGE_TEXT_CHARS = 32768
_LARGE_COLLECTION_ITEMS = 8192
_REQUIRED_PRIMARY_EVENTS = frozenset(
    {
        "session_started",
        "problem_parsed",
        "route_planned",
        "skills_selected",
        "resource_plan_created",
        "hard_evidence_gate",
        "candidate_arbitrated",
        "final_answer_selected",
        "budget_summary",
        "run_completed",
    }
)

# Lower numbers are retained first when bounded trace streams need to evict
# optional events.  The public trace is an accuracy/debugging aid: semantic
# plan, reasoning, verification, arbitration, and finalization information is
# more valuable than transport activity.
TRACE_ACCURACY_PRIORITY = {
    # Tier 0: correctness-critical public semantics.
    "workflow_overview": 0,
    "solution_process": 0,
    "problem_parsed": 0,
    "route_planned": 0,
    "hard_evidence_gate": 0,
    "proof_completion_gate": 0,
    "proof_status_finalized": 0,
    "verification_closure_recomputed": 0,
    "candidate_arbitrated": 0,
    "decision_committed": 0,
    "final_answer_selected": 0,
    "finalization_completed": 0,
    "run_completed": 0,
    # Tier 1: useful supporting semantics.
    "repair_history": 1,
    "repair_completed": 1,
    "repair_committed": 1,
    "candidate_conflict_matrix": 1,
    "peer_review_completed": 1,
    "solver_peer_review_phase_completed": 1,
    "skills_selected": 1,
    "tool_feedback_completed": 1,
    "evidence_summary": 1,
    # Tier 2: activity/transport details are expendable first.
    "model_activity": 2,
    "model_transport_completed": 2,
    "context_view_built": 2,
    "compression_validated": 2,
    "retrieval_completed": 2,
}


def trace_accuracy_priority(event: Any) -> int:
    """Return the eviction priority for an event (lower is more important)."""

    return int(TRACE_ACCURACY_PRIORITY.get(str(event), 1))


# Short alias used by governance/tests that refer to the policy as a table.
TRACE_PRIORITY = TRACE_ACCURACY_PRIORITY
TRACE_PRIORITY_TIERS = {
    "correctness": 0,
    "supporting": 1,
    "activity": 2,
}


class TraceIntegrityError(ValueError):
    pass


class TraceBuilder:
    def __init__(
        self,
        events: list[dict[str, Any]],
        *,
        max_chars: int = 12000,
        max_events: int = 64,
        clock: Callable[[], float] = monotonic,
        redacted_values: Iterable[str] = (),
        event_sink: Callable[[dict[str, Any]], None] | None = None,
        internal_max_events: int = _DEFAULT_INTERNAL_MAX_EVENTS,
    ) -> None:
        if max_chars < 0 or max_events < 0:
            raise ValueError("trace limits must be nonnegative")
        self._events = events
        self._internal_events: list[dict[str, Any]] = []
        self._max_chars = max_chars
        self._max_events = max_events
        self._clock = clock
        self._started_at = clock()
        self._last_elapsed_ms = 0
        self._lock = RLock()
        self._event_sink = event_sink
        self._internal_max_events = max(1, int(internal_max_events))
        self._internal_event_count = 0
        self._internal_events_dropped = 0
        self._journal_failures = 0
        self._frozen = False
        self._redacted_values = tuple(
            value for value in redacted_values if isinstance(value, str) and value
        )

    def add(self, event: str, **details: Any) -> None:
        with self._lock:
            if self._frozen:
                raise RuntimeError("trace is frozen")
            elapsed_ms = self._elapsed_ms()
            internal_details = {
                key: self._sanitize(value)
                for key, value in details.items()
                if not _SENSITIVE_KEYS.search(key)
                and not _PRIVATE_REASONING_KEYS.search(key)
            }
            self._internal_event_count += 1
            debug_item = {
                "schema_version": DEBUG_TRACE_SCHEMA_VERSION,
                "debug_seq": self._internal_event_count,
                "elapsed_ms": elapsed_ms,
                "event": str(event),
                **internal_details,
            }
            self._internal_events.append(debug_item)
            if len(self._internal_events) > self._internal_max_events:
                dropped = len(self._internal_events) - self._internal_max_events
                del self._internal_events[:dropped]
                self._internal_events_dropped += dropped
            if self._event_sink is not None:
                try:
                    self._event_sink(deepcopy(debug_item))
                except Exception:
                    self._journal_failures += 1
            if event not in JUDGE_EVENTS:
                return
            supplied_stage = details.pop("stage", None)
            sanitized = {
                key: self._sanitize(value)
                for key, value in details.items()
                if not _SENSITIVE_KEYS.search(key)
                and not _PRIVATE_REASONING_KEYS.search(key)
            }
            if supplied_stage is not None:
                sanitized["checkpoint"] = self._sanitize(supplied_stage)
            item = {
                "schema_version": TRACE_SCHEMA_VERSION,
                "seq": len(self._events) + 1,
                "elapsed_ms": elapsed_ms,
                "event": event,
                "stage": EVENT_STAGES[event],
                **sanitized,
            }
            self._append_bounded(item)

    def build(self, *, final_response: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            result = deepcopy(self._events)
        if (
            any(
                event.get("schema_version") == TRACE_SCHEMA_VERSION
                for event in result
            )
            and final_response is not None
        ):
            validate_trace_v2(result, final_response=final_response)
        return result

    @property
    def internal_events(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(self._internal_events)

    @property
    def stream_stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "public_events_resident": len(self._events),
                "internal_events_seen": self._internal_event_count,
                "internal_events_resident": len(self._internal_events),
                "internal_events_dropped": self._internal_events_dropped,
                "journal_failures": self._journal_failures,
            }

    def freeze(self) -> None:
        with self._lock:
            self._frozen = True

    @property
    def is_frozen(self) -> bool:
        with self._lock:
            return self._frozen

    def _elapsed_ms(self) -> int:
        elapsed = max(0, int((self._clock() - self._started_at) * 1000))
        self._last_elapsed_ms = max(self._last_elapsed_ms, elapsed)
        return self._last_elapsed_ms

    def _append_bounded(self, item: dict[str, Any]) -> None:
        event = str(item["event"])
        if event in {
            "session_started",
            "closed_loop_health",
            "budget_summary",
            "fallback_used",
            "run_completed",
        }:
            self._events[:] = [
                existing
                for existing in self._events
                if existing.get("event") != event
            ]
        if (
            event not in PROTECTED_TRACE_EVENTS
            and self._events
            and self._same_event_payload(self._events[-1], item)
        ):
            self._events[-1]["repeat_count"] = (
                int(self._events[-1].get("repeat_count", 1)) + 1
            )
            self._events[-1]["elapsed_ms"] = item["elapsed_ms"]
            return
        self._events.append(item)
        while self._max_events > 0 and len(self._events) > self._max_events:
            if not self._evict_unprotected():
                break
        while len(self._events) > _HARD_MAX_PUBLIC_EVENTS:
            if not self._evict_unprotected():
                self._events.pop(1 if len(self._events) > 1 else 0)
        while self._max_chars > 0 and self._serialized_size() > self._max_chars:
            if not self._evict_unprotected():
                break
        self._renumber()

    def _evict_unprotected(self) -> bool:
        candidates = [
            (trace_accuracy_priority(event.get("event")), index)
            for index, event in enumerate(self._events)
            if event.get("event") not in PROTECTED_TRACE_EVENTS
        ]
        if candidates:
            # Evict the least important tier first; ties remove the oldest
            # optional event while preserving newer context.
            _, index = max(candidates, key=lambda item: (item[0], -item[1]))
            self._events.pop(index)
            return True
        return False

    def _renumber(self) -> None:
        for index, event in enumerate(self._events, start=1):
            event["seq"] = index

    def _serialized_size(self) -> int:
        return len(
            json.dumps(
                self._events,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
        )

    @staticmethod
    def _same_event_payload(
        left: dict[str, Any],
        right: dict[str, Any],
    ) -> bool:
        ignored = {"seq", "elapsed_ms", "repeat_count"}
        return {
            key: value for key, value in left.items() if key not in ignored
        } == {
            key: value for key, value in right.items() if key not in ignored
        }

    def _sanitize(self, value: Any, *, allow_large_text: bool = False) -> Any:
        if value is None or isinstance(value, (bool, int)):
            return value
        if isinstance(value, float):
            return value if math.isfinite(value) else str(value)
        if isinstance(value, BaseException):
            return "[redacted-error]"
        if isinstance(value, str):
            if _TRACEBACK_VALUE.search(value):
                return "[redacted-error]"
            sanitized = _API_TOKEN_VALUE.sub("[redacted-secret]", value)
            sanitized = _AUTHORIZATION_VALUE.sub("[redacted-authorization]", sanitized)
            sanitized = _ABSOLUTE_PATH.sub("[local-path]", sanitized)
            for redacted in self._redacted_values:
                sanitized = sanitized.replace(redacted, "[redacted-nonce]")
            if not allow_large_text and len(sanitized) > _LARGE_TEXT_CHARS:
                return {
                    "kind": "text_summary",
                    "chars": len(sanitized),
                    "sha256": sha256(
                        sanitized.encode("utf-8")
                    ).hexdigest(),
                    "preview": sanitized[:512],
                }
            return sanitized
        if isinstance(value, (list, tuple)):
            sanitized_items = [self._sanitize(item) for item in value]
            if len(sanitized_items) > _LARGE_COLLECTION_ITEMS:
                serialized = json.dumps(
                    sanitized_items,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                )
                return {
                    "kind": "collection_summary",
                    "items": sanitized_items[:64],
                    "item_count": len(sanitized_items),
                    "sha256": sha256(serialized.encode("utf-8")).hexdigest(),
                }
            return sanitized_items
        if isinstance(value, dict):
            return {
                str(key): self._sanitize(
                    item,
                    allow_large_text=str(key) == "final_response",
                )
                for key, item in value.items()
                if not _SENSITIVE_KEYS.search(str(key))
                and not _PRIVATE_REASONING_KEYS.search(str(key))
            }
        return f"[{type(value).__name__}]"


def validate_trace_v2(
    trace: list[dict[str, Any]],
    *,
    final_response: str | None = None,
) -> None:
    errors: list[str] = []
    if not trace:
        raise TraceIntegrityError("Trace v2 must not be empty")
    elapsed_values: list[int] = []
    for index, event in enumerate(trace, start=1):
        if not isinstance(event, dict):
            errors.append(f"event {index} is not an object")
            continue
        name = event.get("event")
        if event.get("schema_version") != TRACE_SCHEMA_VERSION:
            errors.append(f"event {index} schema version is invalid")
        if event.get("seq") != index:
            errors.append(f"event {index} sequence is not contiguous")
        elapsed = event.get("elapsed_ms")
        if type(elapsed) is not int or elapsed < 0:
            errors.append(f"event {index} elapsed_ms is invalid")
        else:
            elapsed_values.append(elapsed)
        if name not in JUDGE_EVENTS:
            errors.append(f"event {index} name is not public")
        elif event.get("stage") != EVENT_STAGES[name]:
            errors.append(f"event {index} stage is invalid")
        try:
            restored = json.loads(
                json.dumps(
                    event,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                )
            )
        except (TypeError, ValueError):
            errors.append(f"event {index} is not JSON serializable")
        else:
            if restored != event:
                errors.append(f"event {index} does not JSON round-trip")
        if _contains_sensitive_content(event):
            errors.append(f"event {index} contains unsafe content")
    if elapsed_values != sorted(elapsed_values):
        errors.append("event elapsed_ms values are not monotonic")
    if trace[-1].get("event") != "run_completed":
        errors.append("run_completed must be the final event")

    by_name: dict[str, list[dict[str, Any]]] = {}
    for event in trace:
        if isinstance(event, dict):
            by_name.setdefault(str(event.get("event", "")), []).append(event)
    for required in {"session_started", "budget_summary", "run_completed"}:
        if len(by_name.get(required, [])) != 1:
            errors.append(f"{required} must occur exactly once")

    terminal = by_name.get("run_completed", [{}])[-1]
    outcome = terminal.get("outcome")
    if outcome == "primary":
        missing = sorted(
            event for event in _REQUIRED_PRIMARY_EVENTS if not by_name.get(event)
        )
        if missing:
            errors.append(f"primary trace is missing required events: {missing}")
    elif outcome in {"fallback", "timeout"}:
        if not by_name.get("fallback_used") and not by_name.get("deadline_finalize"):
            errors.append("fallback/timeout trace lacks a terminal reason event")

    starts = [
        str(event.get("candidate_id", ""))
        for event in by_name.get("candidate_generation_started", [])
    ]
    successes = [
        str(event.get("candidate_id", ""))
        for event in by_name.get("candidate_generated", [])
    ]
    failures = [
        str(event.get("candidate_id", ""))
        for event in by_name.get("candidate_generation_failed", [])
    ]
    if len(starts) != len(set(starts)) or any(not candidate_id for candidate_id in starts):
        errors.append("candidate generation start IDs must be unique and non-empty")
    for candidate_id in starts:
        terminal_count = successes.count(candidate_id) + failures.count(candidate_id)
        if terminal_count != 1:
            errors.append(
                f"candidate {candidate_id!r} must have exactly one generation terminal"
            )
    if set(successes + failures) - set(starts):
        errors.append("candidate generation terminal exists without a start")

    candidate_claims: dict[str, set[str]] = {}
    for event in by_name.get("candidate_generated", []):
        candidate_id = str(event.get("candidate_id", ""))
        content = event.get("content", {})
        if not isinstance(content, dict):
            errors.append(f"candidate {candidate_id!r} public content is invalid")
            continue
        if event.get("status") != "generated":
            errors.append(f"candidate {candidate_id!r} status is invalid")
        if not isinstance(event.get("method"), str) or not event.get("method"):
            errors.append(f"candidate {candidate_id!r} method is invalid")
        if "solution_text" in content:
            errors.append(f"candidate {candidate_id!r} exposes full solution_text")
        steps = content.get("public_solution_steps")
        if (
            not isinstance(steps, list)
            or not steps
            or any(not isinstance(step, str) or not step for step in steps)
        ):
            errors.append(f"candidate {candidate_id!r} public steps are invalid")
        answer = content.get("final_answer")
        if not isinstance(answer, str) or not answer.strip():
            errors.append(f"candidate {candidate_id!r} final answer is invalid")
        candidate_claims[candidate_id] = _claim_ids(content, errors, candidate_id)
    for event in by_name.get("candidate_generation_failed", []):
        candidate_id = str(event.get("candidate_id", ""))
        content = event.get("content")
        if event.get("status") != "failed":
            errors.append(f"failed candidate {candidate_id!r} status is invalid")
        if not isinstance(content, dict) or "solution_text" in content:
            errors.append(f"failed candidate {candidate_id!r} content is invalid")

    proposed_ids: set[str] = set()
    for event in by_name.get("repair_proposed", []):
        source = str(event.get("source_candidate_id", ""))
        proposed = str(event.get("proposed_candidate_id", ""))
        if source not in set(successes) | proposed_ids:
            errors.append(f"repair source candidate {source!r} does not exist")
        if not proposed:
            errors.append("repair proposed candidate ID must be non-empty")
        proposed_ids.add(proposed)
        content = event.get("proposed_content", {})
        if isinstance(content, dict):
            candidate_claims[proposed] = _claim_ids(content, errors, proposed)
        else:
            errors.append(f"repair candidate {proposed!r} public content is invalid")

    evidence_events = by_name.get("candidate_evidence_completed", [])
    evidence_candidates = [str(event.get("candidate_id", "")) for event in evidence_events]
    for candidate_id in successes:
        if evidence_candidates.count(candidate_id) != 1:
            errors.append(
                f"generated candidate {candidate_id!r} must have one evidence terminal"
            )
    evidence_ids: set[str] = set()
    for event in evidence_events:
        candidate_id = str(event.get("candidate_id", ""))
        if candidate_id not in candidate_claims:
            errors.append(f"evidence candidate {candidate_id!r} does not exist")
        results = event.get("claim_results", [])
        if not isinstance(results, list):
            errors.append(f"candidate {candidate_id!r} claim_results is invalid")
            continue
        for result in results:
            if not isinstance(result, dict):
                errors.append(f"candidate {candidate_id!r} evidence result is invalid")
                continue
            claim_id = result.get("claim_id")
            if claim_id is not None and str(claim_id) not in candidate_claims.get(
                candidate_id, set()
            ):
                errors.append(
                    f"evidence references unknown claim {candidate_id!r}:{claim_id!r}"
                )
            evidence_id = str(result.get("evidence_id", ""))
            if evidence_id:
                if evidence_id in evidence_ids:
                    errors.append(f"duplicate evidence ID: {evidence_id!r}")
                evidence_ids.add(evidence_id)

    known_candidates = set(starts) | proposed_ids
    arbitrations = by_name.get("candidate_arbitrated", [])
    selected_id = ""
    if arbitrations:
        arbitration = arbitrations[-1]
        selected_id = str(arbitration.get("selected", ""))
        viable = arbitration.get("viable_candidates", [])
        if not isinstance(viable, list):
            errors.append("arbitration viable_candidates is invalid")
            viable = []
        viable_ids = {str(item) for item in viable}
        if viable_ids - known_candidates:
            errors.append("arbitration references a candidate that was not generated")
        if selected_id not in viable_ids:
            errors.append("arbitration selected candidate is not viable")

    final_events = by_name.get("final_answer_selected", [])
    if final_events:
        final_event = final_events[-1]
        if str(final_event.get("candidate_id", "")) != selected_id:
            errors.append("final answer candidate does not match arbitration")
        public_solution = final_event.get("public_solution", {})
        if not isinstance(public_solution, dict):
            errors.append("selected public solution is invalid")
        elif final_response is not None and public_solution.get("final_response") != final_response:
            errors.append("final response does not match selected public solution")
    elif outcome == "primary":
        errors.append("primary trace lacks final_answer_selected")

    _validate_transport_events(by_name, errors)
    _validate_proof_graph_events(
        by_name,
        errors,
        selected_candidate_id=selected_id,
    )
    _validate_case_summary_events(
        by_name,
        errors,
        selected_candidate_id=selected_id,
    )

    session_events = by_name.get("session_started", [])
    session_id = (
        str(session_events[0].get("session_id", ""))
        if len(session_events) == 1
        else ""
    )
    for key, value in _walk_key_values(trace):
        if key == "session_id" and str(value) != session_id:
            errors.append("trace contains a foreign session ID reference")
        if key in {
            "candidate_id",
            "source_candidate_id",
            "proposed_candidate_id",
            "selected_candidate_id",
        } and value is not None and str(value) and str(value) not in known_candidates:
            errors.append(f"trace contains a foreign candidate reference: {value!r}")

    if errors:
        raise TraceIntegrityError("; ".join(dict.fromkeys(errors)))


def _claim_ids(
    content: dict[str, Any],
    errors: list[str],
    candidate_id: str,
) -> set[str]:
    claims = content.get("claims", [])
    if not isinstance(claims, list):
        errors.append(f"candidate {candidate_id!r} claims are invalid")
        return set()
    claim_ids = [
        str(claim.get("claim_id", ""))
        for claim in claims
        if isinstance(claim, dict)
    ]
    if len(claim_ids) != len(claims) or len(claim_ids) != len(set(claim_ids)):
        errors.append(f"candidate {candidate_id!r} claim IDs are invalid")
    return set(claim_ids)


def _walk_key_values(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key), item
            yield from _walk_key_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_key_values(item)


def _contains_sensitive_content(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key)
            if (
                _SENSITIVE_KEYS.search(normalized_key)
                or _PRIVATE_REASONING_KEYS.search(normalized_key)
            ):
                return True
            if _contains_sensitive_content(item):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_sensitive_content(item) for item in value)
    if isinstance(value, str):
        return bool(
            _API_TOKEN_VALUE.search(value)
            or _AUTHORIZATION_VALUE.search(value)
            or _ABSOLUTE_PATH.search(value)
            or _TRACEBACK_VALUE.search(value)
        )
    return False


def _validate_transport_events(
    by_name: dict[str, list[dict[str, Any]]],
    errors: list[str],
) -> None:
    for event in by_name.get("model_transport_completed", []):
        calls = event.get("calls")
        if not isinstance(calls, list):
            errors.append("transport calls must be a list")
            continue
        indexes: list[int] = []
        for call in calls:
            if not isinstance(call, dict):
                errors.append("transport call must be an object")
                continue
            call_index = call.get("call_index")
            if type(call_index) is not int or call_index < 1:
                errors.append("transport call index is invalid")
            else:
                indexes.append(call_index)
            failure_code = str(call.get("failure_code", ""))
            if (
                failure_code
                and failure_code not in SAFE_TRANSPORT_FAILURE_CODES
            ):
                errors.append("transport failure code is unsafe")
        if indexes != list(range(1, len(indexes) + 1)):
            errors.append("transport call indexes are not contiguous")


def _validate_proof_graph_events(
    by_name: dict[str, list[dict[str, Any]]],
    errors: list[str],
    *,
    selected_candidate_id: str,
) -> None:
    for event in by_name.get("proof_graph_completed", []):
        graph = event.get("graph")
        if not isinstance(graph, dict):
            errors.append("proof graph must be an object")
            continue
        if graph.get("schema_version") != PROOF_GRAPH_SCHEMA_VERSION:
            errors.append("proof graph schema version is invalid")
        nodes = graph.get("nodes")
        edges = graph.get("edges")
        if not isinstance(nodes, list) or not isinstance(edges, list):
            errors.append("proof graph nodes and edges must be lists")
            continue
        node_ids = [
            str(node.get("id", ""))
            for node in nodes
            if isinstance(node, dict)
        ]
        if (
            len(node_ids) != len(nodes)
            or any(not node_id for node_id in node_ids)
            or len(node_ids) != len(set(node_ids))
        ):
            errors.append("proof graph node IDs are invalid")
        known_nodes = set(node_ids)
        for edge in edges:
            if (
                not isinstance(edge, dict)
                or str(edge.get("from", "")) not in known_nodes
                or str(edge.get("to", "")) not in known_nodes
                or not str(edge.get("relation", ""))
            ):
                errors.append("proof graph edge reference is invalid")
        graph_selected = str(graph.get("selected_candidate_id", ""))
        if graph_selected != selected_candidate_id:
            errors.append("proof graph selected candidate is inconsistent")


def _validate_case_summary_events(
    by_name: dict[str, list[dict[str, Any]]],
    errors: list[str],
    *,
    selected_candidate_id: str,
) -> None:
    for event in by_name.get("case_trace_summary", []):
        summary = event.get("summary")
        if not isinstance(summary, dict):
            errors.append("case trace summary must be an object")
            continue
        if summary.get("schema_version") != CASE_SUMMARY_SCHEMA_VERSION:
            errors.append("case trace summary schema version is invalid")
        if (
            str(summary.get("selected_candidate_id", ""))
            != selected_candidate_id
        ):
            errors.append("case trace summary selected candidate is inconsistent")
        if not isinstance(summary.get("decision_path"), list):
            errors.append("case trace summary decision path is invalid")
