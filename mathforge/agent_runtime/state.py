from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from threading import RLock
from typing import Any

from mathforge.agent_runtime.definitions import AgentRegistry


TERMINAL_AGENT_STATES = frozenset({"completed", "abstained", "failed", "cancelled"})
_TRANSITIONS = {
    "created": frozenset({"ready", "cancelled"}),
    "ready": frozenset({"running", "completed", "abstained", "failed", "cancelled"}),
    "running": frozenset({"ready", "waiting_message", "waiting_evidence", "waiting_resource", "completed", "abstained", "failed", "cancelled"}),
    "waiting_message": frozenset({"ready", "running", "completed", "failed", "cancelled"}),
    "waiting_evidence": frozenset({"ready", "running", "completed", "failed", "cancelled"}),
    "waiting_resource": frozenset({"ready", "running", "completed", "failed", "cancelled"}),
}


@dataclass(frozen=True)
class AgentInstance:
    agent_id: str
    session_id: str
    role: str
    mode: str
    descriptor: str


@dataclass(frozen=True)
class AgentState:
    agent_id: str
    status: str = "created"
    current_task_id: str = ""
    accepted_task_ids: tuple[str, ...] = ()
    input_artifact_ids: tuple[str, ...] = ()
    output_artifact_ids: tuple[str, ...] = ()
    unread_message_ids: tuple[str, ...] = ()
    conversation_thread_ids: tuple[str, ...] = ()
    model_call_count: int = 0
    budget_snapshot: dict[str, Any] = field(default_factory=dict)
    failure_code: str = ""

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(asdict(self))


@dataclass(frozen=True)
class AgentTask:
    task_id: str
    session_id: str
    task_type: str
    assigned_agent_id: str
    status: str = "created"
    parent_task_id: str = ""
    input_artifact_ids: tuple[str, ...] = ()
    output_artifact_ids: tuple[str, ...] = ()
    created_sequence: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AgentStateRegistry:
    def __init__(self, session_id: str, definitions: AgentRegistry) -> None:
        self.session_id = session_id
        self._definitions = definitions
        self._instances: dict[str, AgentInstance] = {}
        self._states: dict[str, AgentState] = {}
        self._lock = RLock()

    def create(self, instance: AgentInstance) -> AgentState:
        with self._lock:
            if instance.session_id != self.session_id:
                raise ValueError("cross-session AgentInstance rejected")
            definition = self._definitions.get(instance.role)
            if instance.mode not in definition.allowed_modes:
                raise ValueError("AgentInstance mode is not allowed")
            if instance.agent_id in self._instances:
                return self._states[instance.agent_id]
            self._instances[instance.agent_id] = instance
            self._states[instance.agent_id] = AgentState(instance.agent_id, status="ready")
            return self._states[instance.agent_id]

    def exists(self, agent_id: str) -> bool:
        with self._lock:
            return agent_id in self._instances

    def instance(self, agent_id: str) -> AgentInstance:
        with self._lock:
            return self._instances[agent_id]

    def transition(self, agent_id: str, target: str, *, failure_code: str = "") -> AgentState:
        with self._lock:
            state = self._states[agent_id]
            if target == state.status:
                return state
            if target not in _TRANSITIONS.get(state.status, frozenset()):
                raise RuntimeError(f"invalid Agent transition {state.status}->{target}")
            state = replace(state, status=target, failure_code=str(failure_code))
            self._states[agent_id] = state
            return state

    def update(self, agent_id: str, **changes: Any) -> AgentState:
        with self._lock:
            state = replace(self._states[agent_id], **changes)
            self._states[agent_id] = state
            return state

    def append(self, agent_id: str, field_name: str, value: str) -> AgentState:
        with self._lock:
            current = self._states[agent_id]
            values = getattr(current, field_name)
            if value not in values:
                current = replace(current, **{field_name: (*values, value)})
                self._states[agent_id] = current
            return current

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = []
            for agent_id, instance in self._instances.items():
                rows.append({**asdict(instance), "state": self._states[agent_id].to_dict()})
            return rows

    def clear(self) -> None:
        with self._lock:
            self._instances.clear()
            self._states.clear()


class AgentTaskRegistry:
    def __init__(self, session_id: str, agents: AgentStateRegistry, definitions: AgentRegistry) -> None:
        self.session_id = session_id
        self._agents = agents
        self._definitions = definitions
        self._tasks: dict[str, AgentTask] = {}
        self._sequence = 0
        self._lock = RLock()

    def create(self, task_type: str, agent_id: str, *, parent_task_id: str = "") -> AgentTask:
        with self._lock:
            instance = self._agents.instance(agent_id)
            if instance.session_id != self.session_id:
                raise ValueError("cross-session task rejected")
            if task_type not in self._definitions.get(instance.role).accepted_task_types:
                raise PermissionError("Agent cannot accept task type")
            if parent_task_id and parent_task_id not in self._tasks:
                raise ValueError("parent task does not exist")
            self._sequence += 1
            task_id = f"task-{self.session_id[:8]}-{self._sequence:04d}"
            task = AgentTask(task_id, self.session_id, task_type, agent_id, status="ready", parent_task_id=parent_task_id, created_sequence=self._sequence)
            self._tasks[task_id] = task
            self._agents.append(agent_id, "accepted_task_ids", task_id)
            self._agents.update(agent_id, current_task_id=task_id)
            return task

    def transition(self, task_id: str, status: str) -> AgentTask:
        with self._lock:
            task = self._tasks[task_id]
            allowed = {"created": {"ready"}, "ready": {"running", "completed", "failed", "cancelled"}, "running": {"ready", "completed", "failed", "cancelled"}}
            if status != task.status and status not in allowed.get(task.status, set()):
                raise RuntimeError(f"invalid AgentTask transition {task.status}->{status}")
            task = replace(task, status=status)
            self._tasks[task_id] = task
            return task

    def append_output(self, task_id: str, artifact_id: str) -> None:
        with self._lock:
            task = self._tasks[task_id]
            if artifact_id not in task.output_artifact_ids:
                self._tasks[task_id] = replace(task, output_artifact_ids=(*task.output_artifact_ids, artifact_id))

    def get(self, task_id: str) -> AgentTask:
        with self._lock:
            return self._tasks[task_id]

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [task.to_dict() for task in self._tasks.values()]

    def clear(self) -> None:
        with self._lock:
            self._tasks.clear()
