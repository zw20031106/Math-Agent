from __future__ import annotations

from copy import deepcopy
import json
import math
import re
from time import monotonic
from typing import Any, Callable, Iterable

from mathforge.harness.events import (
    EVENT_STAGES,
    JUDGE_EVENTS,
    PROTECTED_TRACE_EVENTS,
    TRACE_SCHEMA_VERSION,
)


_SENSITIVE_KEYS = re.compile(
    r"^(?:"
    r"secret|.*[_-]secret|password|passwd|.*[_-]password|api[_-]?key|"
    r".*[_-]api[_-]?key|(?:access|auth|bearer|refresh|private|session|id)[_-]?token|"
    r"authorization|credentials?|exception|traceback|.*nonce"
    r")$",
    re.I,
)
_ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:\\|/(?:home|Users|root|tmp)/)[^\s]+")
_API_TOKEN_VALUE = re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}")
_AUTHORIZATION_VALUE = re.compile(r"\b(?:authorization\s*:?\s*)?bearer\s+\S+", re.I)
_TRACEBACK_VALUE = re.compile(r"\btraceback\s*\(most recent call last\)", re.I)
_REQUIRED_PRIMARY_EVENTS = frozenset(
    {
        "session_started",
        "problem_parsed",
        "route_planned",
        "skills_selected",
        "call_allocation_planned",
        "hard_evidence_gate",
        "candidate_arbitrated",
        "final_answer_selected",
        "budget_summary",
        "run_completed",
    }
)


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
    ) -> None:
        self._events = events
        self._internal_events: list[dict[str, Any]] = []
        self._max_chars = max_chars
        self._max_events = max_events
        self._clock = clock
        self._started_at = clock()
        self._last_elapsed_ms = 0
        self._redacted_values = tuple(
            value for value in redacted_values if isinstance(value, str) and value
        )

    def add(self, event: str, **details: Any) -> None:
        self._internal_events.append({"event": event, **deepcopy(details)})
        if event not in JUDGE_EVENTS:
            return
        supplied_stage = details.pop("stage", None)
        sanitized = {
            key: self._sanitize(value)
            for key, value in details.items()
            if not _SENSITIVE_KEYS.search(key)
        }
        if supplied_stage is not None:
            sanitized["checkpoint"] = self._sanitize(supplied_stage)
        item = {
            "schema_version": TRACE_SCHEMA_VERSION,
            "seq": len(self._events) + 1,
            "elapsed_ms": self._elapsed_ms(),
            "event": event,
            "stage": EVENT_STAGES[event],
            **sanitized,
        }
        self._append_bounded(item)

    def build(self, *, final_response: str | None = None) -> list[dict[str, Any]]:
        result = deepcopy(self._events)
        if (
            any(
                event.get("schema_version") == TRACE_SCHEMA_VERSION
                for event in result
            )
            and any(event.get("event") == "run_completed" for event in result)
        ):
            validate_trace_v2(result, final_response=final_response)
        return result

    @property
    def internal_events(self) -> list[dict[str, Any]]:
        return deepcopy(self._internal_events)

    def _elapsed_ms(self) -> int:
        elapsed = max(0, int((self._clock() - self._started_at) * 1000))
        self._last_elapsed_ms = max(self._last_elapsed_ms, elapsed)
        return self._last_elapsed_ms

    def _append_bounded(self, item: dict[str, Any]) -> None:
        event = str(item["event"])
        if event in {"session_started", "budget_summary", "fallback_used", "run_completed"}:
            self._events[:] = [
                existing
                for existing in self._events
                if existing.get("event") != event
            ]
        self._events.append(item)
        while self._max_events > 0 and len(self._events) > self._max_events:
            if not self._evict_unprotected():
                break
        while self._max_chars > 0 and self._serialized_size() > self._max_chars:
            if not self._evict_unprotected():
                break
        self._renumber()

    def _evict_unprotected(self) -> bool:
        for index in range(len(self._events) - 1, -1, -1):
            if self._events[index].get("event") not in PROTECTED_TRACE_EVENTS:
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

    def _sanitize(self, value: Any) -> Any:
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
            return sanitized
        if isinstance(value, (list, tuple)):
            return [self._sanitize(item) for item in value]
        if isinstance(value, dict):
            return {
                str(key): self._sanitize(item)
                for key, item in value.items()
                if not _SENSITIVE_KEYS.search(str(key))
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
        } and value is not None and str(value) not in known_candidates:
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
