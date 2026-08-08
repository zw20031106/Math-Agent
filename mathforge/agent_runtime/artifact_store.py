from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from threading import RLock
from typing import Any

from mathforge.agent_runtime.definitions import AgentRegistry
from mathforge.agent_runtime.protocol import ARTIFACT_TYPES, PROTOCOL_SCHEMA_VERSION
from mathforge.agent_runtime.state import AgentStateRegistry


def stable_payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ArtifactEnvelope:
    artifact_id: str
    session_id: str
    artifact_type: str
    producer_agent_id: str
    task_id: str
    turn_id: str
    version: int
    parent_artifact_ids: tuple[str, ...]
    payload_sha256: str
    payload: dict[str, Any]
    schema_version: str = PROTOCOL_SCHEMA_VERSION
    producer_kind: str = "agent"
    producer_service_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(asdict(self))


class SessionArtifactStore:
    def __init__(self, session_id: str, agents: AgentStateRegistry, definitions: AgentRegistry) -> None:
        self.session_id = session_id
        self._agents = agents
        self._definitions = definitions
        self._records: dict[str, ArtifactEnvelope] = {}
        self._sequence = 0
        self._lock = RLock()

    def publish(self, *, artifact_type: str, producer_agent_id: str, task_id: str, turn_id: str, payload: dict[str, Any], parent_artifact_ids: tuple[str, ...] = ()) -> ArtifactEnvelope:
        with self._lock:
            if artifact_type not in ARTIFACT_TYPES:
                raise ValueError("unknown artifact type")
            instance = self._agents.instance(producer_agent_id)
            if instance.session_id != self.session_id:
                raise ValueError("cross-session artifact rejected")
            if artifact_type not in self._definitions.get(instance.role).writable_artifact_types:
                raise PermissionError("Agent cannot write artifact type")
            for parent_id in parent_artifact_ids:
                if parent_id not in self._records:
                    raise ValueError("parent artifact does not exist in session")
            safe_payload = deepcopy(payload)
            digest = stable_payload_hash(safe_payload)
            self._sequence += 1
            artifact_id = f"art-{self.session_id[:8]}-{self._sequence:04d}-{digest[:10]}"
            envelope = ArtifactEnvelope(artifact_id, self.session_id, artifact_type, producer_agent_id, task_id, turn_id, 1, tuple(parent_artifact_ids), digest, safe_payload)
            self._records[artifact_id] = envelope
            return ArtifactEnvelope(**envelope.to_dict())

    def publish_deterministic_decision(
        self,
        *,
        payload: dict[str, Any],
        parent_artifact_ids: tuple[str, ...],
    ) -> ArtifactEnvelope:
        """Publish the Host arbitration result without impersonating an LLM Agent."""

        with self._lock:
            for parent_id in parent_artifact_ids:
                if parent_id not in self._records:
                    raise ValueError("parent artifact does not exist in session")
            safe_payload = deepcopy(payload)
            digest = stable_payload_hash(safe_payload)
            self._sequence += 1
            artifact_id = (
                f"art-{self.session_id[:8]}-{self._sequence:04d}-{digest[:10]}"
            )
            envelope = ArtifactEnvelope(
                artifact_id=artifact_id,
                session_id=self.session_id,
                artifact_type="DecisionArtifact",
                producer_agent_id="",
                task_id="",
                turn_id="",
                version=1,
                parent_artifact_ids=tuple(parent_artifact_ids),
                payload_sha256=digest,
                payload=safe_payload,
                producer_kind="deterministic_service",
                producer_service_id="DeterministicArbitrator",
            )
            self._records[artifact_id] = envelope
            return ArtifactEnvelope(**envelope.to_dict())

    def get(self, artifact_id: str, *, reader_agent_id: str = "") -> ArtifactEnvelope:
        with self._lock:
            envelope = self._records[artifact_id]
            if reader_agent_id:
                instance = self._agents.instance(reader_agent_id)
                if envelope.artifact_type not in self._definitions.get(instance.role).readable_artifact_types:
                    raise PermissionError("Agent cannot read artifact type")
            return ArtifactEnvelope(**envelope.to_dict())

    def exists(self, artifact_id: str) -> bool:
        with self._lock:
            return artifact_id in self._records

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [item.to_dict() for item in self._records.values()]

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
