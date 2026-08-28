"""Separate, sanitized evaluation artifacts for the public participant result.

The official wrapper receives only the four-field public result.  This module
provides an opt-in local sink for the richer run record used to diagnose
accuracy, latency, and completion failures without widening that contract.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path
import re
from threading import Lock
from typing import Any, Iterable, Protocol


EVALUATION_ARTIFACT_SCHEMA_VERSION = "1.0"
EVALUATION_ARTIFACT_SECTIONS = (
    "run_metrics",
    "provider_telemetry",
    "prompt_snapshot",
    "skill_selection",
    "task_graph",
    "candidate_provenance",
    "evidence",
    "completion",
    "failure_attribution",
)
_PRIVATE_KEY = re.compile(
    r"(?i)(?:api[_-]?key|authorization|password|secret|token|raw[_-]?(?:prompt|response|completion)|chain[_-]?of[_-]?thought|scratchpad|private[_-]?reasoning|internal[_-]?prompt|traceback|exception)"
)
_ABSOLUTE_PATH = re.compile(r"(?:(?:[A-Za-z]:[\\/])|/(?:home|Users|root|tmp)/)[^\s,;]+")
_ALLOWED_CONTROL = frozenset({"\n", "\r", "\t"})


class EvaluationArtifactSink(Protocol):
    def record(self, payload: dict[str, Any]) -> None: ...


class InMemoryEvaluationArtifactSink:
    """Thread-safe sink used by tests and local diagnostics."""

    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []
        self._lock = Lock()

    @property
    def records(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(self._records)

    def record(self, payload: dict[str, Any]) -> None:
        artifact = EvaluationArtifact.from_dict(payload)
        with self._lock:
            self._records.append(artifact.to_dict())


class JsonlEvaluationArtifactSink:
    """Append-only local artifact sink physically separate from public JSON."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def record(self, payload: dict[str, Any]) -> None:
        serialized = json.dumps(
            EvaluationArtifact.from_dict(payload).to_dict(),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        with self._lock:
            with self._path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(serialized + "\n")


@dataclass(frozen=True)
class EvaluationArtifact:
    """Schema-stable diagnostic record; never part of the public contract."""

    case_id: str = ""
    session_id: str = ""
    outcome: str = "error"
    run_metrics: dict[str, Any] = field(default_factory=dict)
    provider_telemetry: dict[str, Any] = field(default_factory=dict)
    prompt_snapshot: dict[str, Any] = field(default_factory=dict)
    skill_selection: dict[str, Any] = field(default_factory=dict)
    task_graph: dict[str, Any] = field(default_factory=dict)
    candidate_provenance: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    completion: dict[str, Any] = field(default_factory=dict)
    failure_attribution: dict[str, Any] = field(default_factory=dict)
    public_result_digest: str = ""
    schema_version: str = EVALUATION_ARTIFACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if self.schema_version != EVALUATION_ARTIFACT_SCHEMA_VERSION:
            raise ValueError("unsupported evaluation artifact schema version")
        for name in ("case_id", "session_id", "outcome", "public_result_digest"):
            if not isinstance(getattr(self, name), str):
                raise ValueError(f"evaluation artifact {name} must be a string")
        for name in EVALUATION_ARTIFACT_SECTIONS:
            value = getattr(self, name)
            if name == "candidate_provenance":
                if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
                    raise ValueError("candidate_provenance must be a list of objects")
            elif not isinstance(value, dict):
                raise ValueError(f"evaluation artifact {name} must be an object")
        _validate_safe(self.to_dict(include_schema=False))

    def to_dict(self, *, include_schema: bool = True) -> dict[str, Any]:
        payload = {
            "case_id": self.case_id,
            "session_id": self.session_id,
            "outcome": self.outcome,
            "run_metrics": _safe_value(self.run_metrics),
            "provider_telemetry": _safe_value(self.provider_telemetry),
            "prompt_snapshot": _safe_value(self.prompt_snapshot),
            "skill_selection": _safe_value(self.skill_selection),
            "task_graph": _safe_value(self.task_graph),
            "candidate_provenance": _safe_value(self.candidate_provenance),
            "evidence": _safe_value(self.evidence),
            "completion": _safe_value(self.completion),
            "failure_attribution": _safe_value(self.failure_attribution),
            "public_result_digest": self.public_result_digest,
        }
        if include_schema:
            payload["schema_version"] = self.schema_version
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EvaluationArtifact":
        if not isinstance(payload, dict):
            raise ValueError("evaluation artifact must be an object")
        required = {
            "case_id",
            "session_id",
            "outcome",
            *EVALUATION_ARTIFACT_SECTIONS,
            "public_result_digest",
            "schema_version",
        }
        if set(payload) != required:
            raise ValueError("evaluation artifact fields do not match schema")
        return cls(
            case_id=str(payload["case_id"]),
            session_id=str(payload["session_id"]),
            outcome=str(payload["outcome"]),
            run_metrics=dict(payload["run_metrics"]),
            provider_telemetry=dict(payload["provider_telemetry"]),
            prompt_snapshot=dict(payload["prompt_snapshot"]),
            skill_selection=dict(payload["skill_selection"]),
            task_graph=dict(payload["task_graph"]),
            candidate_provenance=[dict(item) for item in payload["candidate_provenance"]],
            evidence=dict(payload["evidence"]),
            completion=dict(payload["completion"]),
            failure_attribution=dict(payload["failure_attribution"]),
            public_result_digest=str(payload["public_result_digest"]),
            schema_version=str(payload["schema_version"]),
        )


def build_evaluation_artifact(
    *,
    case_id: Any = "",
    session_id: Any = "",
    outcome: str = "error",
    run_metrics: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
    internal_events: Iterable[dict[str, Any]] = (),
    provider_telemetry: dict[str, Any] | None = None,
    task_graph: dict[str, Any] | None = None,
    candidate_provenance: Iterable[Any] = (),
    evidence: Iterable[Any] = (),
    completion: dict[str, Any] | None = None,
    failure_attribution: dict[str, Any] | None = None,
    public_result: dict[str, Any] | None = None,
) -> EvaluationArtifact:
    events = [item for item in internal_events if isinstance(item, dict)]
    event_names = [str(item.get("event", "")) for item in events]
    candidates = []
    for candidate in candidate_provenance:
        candidate_id = str(getattr(candidate, "candidate_id", ""))
        if not candidate_id and isinstance(candidate, dict):
            candidate_id = str(candidate.get("candidate_id", ""))
        provenance_value = getattr(candidate, "cognitive_provenance", None)
        if not isinstance(provenance_value, dict):
            provenance_value = (
                candidate.get("provenance", {})
                if isinstance(candidate, dict)
                else {}
            )
        candidates.append(
            _safe_value(
                {
                    "candidate_id": candidate_id,
                    "version": _positive_int(
                        getattr(candidate, "version", candidate.get("version", 1) if isinstance(candidate, dict) else 1)
                    ),
                    "branch_id": str(
                        getattr(candidate, "branch_id", candidate.get("branch_id", "") if isinstance(candidate, dict) else "")
                    ),
                    "method_family": str(
                        getattr(candidate, "method_family", candidate.get("method_family", "") if isinstance(candidate, dict) else "")
                    ),
                    "model_identity": str(
                        getattr(candidate, "model_identity", candidate.get("model_identity", "") if isinstance(candidate, dict) else "")
                    ),
                    "provenance": provenance_value,
                }
            )
        )
    evidence_items = []
    for record in evidence:
        evidence_items.append(
            {
                "evidence_id": str(getattr(record, "evidence_id", "")),
                "candidate_id": str(getattr(record, "candidate_id", "")),
                "claim_id": str(getattr(record, "claim_id", "")),
                "status": str(getattr(record, "status", "")),
                "strength": str(getattr(record, "strength", "")),
                "transaction_status": str(getattr(record, "transaction_status", "")),
                "evidence_type": str(getattr(record, "evidence_type", "")),
            }
        )
    skill_event = _last_event(events, "skills_selected")
    skill_selection = _select_fields(
        skill_event,
        ("selected", "skills", "skill_names", "skill_set_hash", "selection_reason", "count"),
    )
    task_events = [
        _select_fields(
            event,
            ("event", "node_id", "task_id", "role", "action", "state", "status", "generation", "plan_version"),
        )
        for event in events
        if str(event.get("event", "")).startswith("scheduler_")
        or str(event.get("event", "")) == "scheduler_task_graph_created"
    ]
    prompt_snapshot = {
        "event_count": len(events),
        "context_events": sum(name in {"context_view_built", "compression_validated"} for name in event_names),
        "roles": sorted(
            {
                str(event.get("role", ""))
                for event in events
                if str(event.get("role", "")).strip()
            }
        ),
        "prompt_hashes": sorted(
            {
                str(event.get(key, ""))
                for event in events
                for key in ("prompt_hash", "context_hash", "request_fingerprint")
                if str(event.get(key, "")).strip()
            }
        ),
        "run_provenance": _safe_value(provenance or {}),
    }
    completion_payload = dict(completion or {})
    for name in ("proof_status_finalized", "verification_closure_recomputed", "run_completed"):
        event = _last_event(events, name)
        if event:
            completion_payload[name] = _select_fields(
                event,
                ("event", "outcome", "statuses", "closures", "final_phase", "error_code"),
            )
    failure_payload = dict(failure_attribution or {})
    if not failure_payload:
        failure_payload = _select_fields(
            _last_event(events, "closed_loop_health"),
            ("health", "root_failure_code", "selected_candidate_id", "outcome"),
        )
    public_digest = ""
    if isinstance(public_result, dict):
        public_digest = sha256(
            json.dumps(
                {
                    "id": public_result.get("id"),
                    "status": public_result.get("status"),
                    "final_response": public_result.get("final_response"),
                    "trace": public_result.get("trace"),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    task_graph_payload = dict(task_graph or {})
    task_graph_payload.setdefault("events", task_events)
    artifact = EvaluationArtifact(
        case_id=str(case_id),
        session_id=str(session_id),
        outcome=str(outcome),
        run_metrics=_safe_value(run_metrics or {}),
        provider_telemetry=_safe_value(provider_telemetry or {}),
        prompt_snapshot=_safe_value(prompt_snapshot),
        skill_selection=_safe_value(skill_selection),
        task_graph=_safe_value(task_graph_payload),
        candidate_provenance=candidates,
        evidence={
            "records": _safe_value(evidence_items),
            "active_count": sum(item["transaction_status"] == "active" for item in evidence_items),
        },
        completion=_safe_value(completion_payload),
        failure_attribution=_safe_value(failure_payload),
        public_result_digest=public_digest,
    )
    return artifact


def _last_event(events: list[dict[str, Any]], name: str) -> dict[str, Any]:
    return next(
        (event for event in reversed(events) if str(event.get("event", "")) == name),
        {},
    )


def _select_fields(event: dict[str, Any], names: Iterable[str]) -> dict[str, Any]:
    return {name: event[name] for name in names if name in event}


def _safe_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        return "[depth-limited]"
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if value == value and value not in {float("inf"), float("-inf")} else str(value)
    if isinstance(value, str):
        cleaned = _ABSOLUTE_PATH.sub("[local-path]", value)
        cleaned = "".join(
            character if character in _ALLOWED_CONTROL or ord(character) >= 32 else " "
            for character in cleaned
        )
        return cleaned[:4096]
    if isinstance(value, (list, tuple)):
        return [_safe_value(item, depth=depth + 1) for item in list(value)[:256]]
    if isinstance(value, dict):
        return {
            str(key): _safe_value(item, depth=depth + 1)
            for key, item in list(value.items())[:256]
            if not _PRIVATE_KEY.search(str(key))
        }
    return _safe_value(str(value), depth=depth + 1)


def _validate_safe(value: Any) -> None:
    if isinstance(value, str):
        if any(ord(character) < 32 and character not in _ALLOWED_CONTROL for character in value):
            raise ValueError("evaluation artifact contains an unsafe control character")
    elif isinstance(value, list):
        for item in value:
            _validate_safe(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            _validate_safe(str(key))
            _validate_safe(item)


def _positive_int(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 1
    return number if number > 0 else 1


__all__ = [
    "EVALUATION_ARTIFACT_SCHEMA_VERSION",
    "EVALUATION_ARTIFACT_SECTIONS",
    "EvaluationArtifact",
    "EvaluationArtifactSink",
    "InMemoryEvaluationArtifactSink",
    "JsonlEvaluationArtifactSink",
    "build_evaluation_artifact",
]
