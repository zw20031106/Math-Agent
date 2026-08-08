from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
from threading import RLock
from typing import Any

from mathforge.agent_runtime.artifact_store import SessionArtifactStore
from mathforge.agent_runtime.definitions import AgentRegistry
from mathforge.agent_runtime.protocol import MESSAGE_TYPES, PROTOCOL_SCHEMA_VERSION
from mathforge.agent_runtime.state import AgentStateRegistry, AgentTaskRegistry


@dataclass(frozen=True)
class MessageEnvelope:
    message_id: str
    session_id: str
    thread_id: str
    sender_agent_id: str
    recipient_agent_id: str
    task_id: str
    message_type: str
    artifact_ids: tuple[str, ...]
    reply_to_message_id: str
    public_summary: str
    sequence: int
    schema_version: str = PROTOCOL_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ConversationThread:
    thread_id: str
    session_id: str
    participant_agent_ids: tuple[str, ...]
    message_ids: tuple[str, ...] = ()
    status: str = "open"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SessionMailbox:
    def __init__(self, session_id: str, agents: AgentStateRegistry, tasks: AgentTaskRegistry, artifacts: SessionArtifactStore, definitions: AgentRegistry) -> None:
        self.session_id = session_id
        self._agents = agents
        self._tasks = tasks
        self._artifacts = artifacts
        self._definitions = definitions
        self._threads: dict[str, ConversationThread] = {}
        self._messages: dict[str, MessageEnvelope] = {}
        self._dedupe: dict[str, str] = {}
        self._sequence = 0
        self._thread_sequence = 0
        self._lock = RLock()

    def create_thread(self, participant_agent_ids: tuple[str, ...]) -> ConversationThread:
        with self._lock:
            participants = tuple(dict.fromkeys(participant_agent_ids))
            if len(participants) < 2 or any(not self._agents.exists(item) for item in participants):
                raise ValueError("conversation participants must be same-session Agents")
            self._thread_sequence += 1
            thread_id = f"thread-{self.session_id[:8]}-{self._thread_sequence:04d}"
            thread = ConversationThread(thread_id, self.session_id, participants)
            self._threads[thread_id] = thread
            for agent_id in participants:
                self._agents.append(agent_id, "conversation_thread_ids", thread_id)
            return thread

    def send(self, *, thread_id: str, sender_agent_id: str, recipient_agent_id: str, task_id: str, message_type: str, artifact_ids: tuple[str, ...], public_summary: str, reply_to_message_id: str = "") -> MessageEnvelope:
        with self._lock:
            thread = self._threads[thread_id]
            if thread.status != "open":
                raise RuntimeError("conversation is closed")
            if sender_agent_id not in thread.participant_agent_ids or recipient_agent_id not in thread.participant_agent_ids:
                raise ValueError("message participant is outside conversation")
            if self._tasks.get(task_id).session_id != self.session_id:
                raise ValueError("cross-session task reference rejected")
            if message_type not in MESSAGE_TYPES or message_type not in self._definitions.get(self._agents.instance(recipient_agent_id).role).accepted_message_types:
                raise PermissionError("recipient does not accept message type")
            if not artifact_ids or any(not self._artifacts.exists(item) for item in artifact_ids):
                raise ValueError("message requires valid artifact references")
            summary = str(public_summary).strip()
            if not summary:
                raise ValueError("public summary is required")
            semantic = json.dumps([thread_id, sender_agent_id, recipient_agent_id, task_id, message_type, artifact_ids, reply_to_message_id, summary], ensure_ascii=False, separators=(",", ":"))
            key = sha256(semantic.encode("utf-8")).hexdigest()
            if key in self._dedupe:
                return self._messages[self._dedupe[key]]
            if thread.message_ids and not reply_to_message_id:
                raise ValueError("conversation reply_to is required")
            if reply_to_message_id:
                parent = self._messages.get(reply_to_message_id)
                if parent is None or parent.thread_id != thread_id:
                    raise ValueError("reply_to message is invalid")
                if set(artifact_ids) <= set(parent.artifact_ids):
                    raise ValueError("reply must add a new artifact")
            self._sequence += 1
            message_id = f"msg-{self.session_id[:8]}-{self._sequence:04d}"
            message = MessageEnvelope(message_id, self.session_id, thread_id, sender_agent_id, recipient_agent_id, task_id, message_type, tuple(artifact_ids), reply_to_message_id, summary[:512], self._sequence)
            self._messages[message_id] = message
            self._dedupe[key] = message_id
            self._threads[thread_id] = replace(thread, message_ids=(*thread.message_ids, message_id))
            self._agents.append(recipient_agent_id, "unread_message_ids", message_id)
            return message

    def close(self, thread_id: str) -> ConversationThread:
        with self._lock:
            thread = self._threads[thread_id]
            thread = replace(thread, status="closed")
            self._threads[thread_id] = thread
            return thread

    def reopen(
        self,
        thread_id: str,
        *,
        new_artifact_id: str,
    ) -> ConversationThread:
        with self._lock:
            thread = self._threads[thread_id]
            if thread.status != "closed":
                raise RuntimeError("conversation is already open")
            if not self._artifacts.exists(new_artifact_id):
                raise ValueError("reopen requires a valid new Artifact")
            prior_artifacts = {
                artifact_id
                for message_id in thread.message_ids
                for artifact_id in self._messages[message_id].artifact_ids
            }
            if new_artifact_id in prior_artifacts:
                raise ValueError("reopen requires new public content")
            thread = replace(thread, status="open")
            self._threads[thread_id] = thread
            return thread

    def latest_message_id(self, thread_id: str) -> str:
        with self._lock:
            ids = self._threads[thread_id].message_ids
            return ids[-1] if ids else ""

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        with self._lock:
            return {"messages": [deepcopy(item.to_dict()) for item in self._messages.values()], "threads": [deepcopy(item.to_dict()) for item in self._threads.values()]}

    def clear(self) -> None:
        with self._lock:
            self._threads.clear()
            self._messages.clear()
            self._dedupe.clear()
