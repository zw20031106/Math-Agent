from __future__ import annotations

from concurrent.futures import ALL_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field, replace
from hashlib import sha256
from threading import Event, Lock
from time import perf_counter
from typing import Callable, Iterable, Iterator, Mapping, TypeVar

from mathforge.harness.cancellation import CancellationToken
from mathforge.harness.errors import ModelCallRejected
from mathforge.harness.model_policy import stage_sequence_reserve_seconds


T = TypeVar("T")
TASK_GRAPH_SCHEMA_VERSION = "1.0"
GRAPH_NODE_STATES = frozenset(
    {"pending", "ready", "running", "completed", "failed", "skipped", "cancelled"}
)
# ``blocked`` and ``stale`` are retained only as compatibility projections of
# the pre-E5 ``SchedulerFlow.run_graph`` API; the authoritative executor uses
# the seven states above for dispatch and terminal decisions.
GRAPH_TERMINAL_STATES = frozenset(
    {*GRAPH_NODE_STATES, "blocked", "stale"}
)


@dataclass(frozen=True)
class SchedulerTaskBinding:
    """Model-call identity supplied by the authoritative graph executor."""

    scheduler_task_id: str
    plan_version: int
    agent_id: str
    turn_id: str = ""
    wave_generation: int = 0
    graph_id: str = ""
    required: bool = True

    def __post_init__(self) -> None:
        if not self.scheduler_task_id or not self.agent_id:
            raise ValueError("scheduler task binding requires task and agent identities")
        if self.plan_version < 0 or self.wave_generation < 0:
            raise ValueError("scheduler task binding versions must be nonnegative")
        if type(self.required) is not bool:
            raise ValueError("scheduler task binding required flag must be boolean")

    def to_dict(self) -> dict[str, object]:
        return {
            "scheduler_task_id": self.scheduler_task_id,
            "plan_version": self.plan_version,
            "agent_id": self.agent_id,
            "turn_id": self.turn_id,
            "wave_generation": self.wave_generation,
            "graph_id": self.graph_id,
            "required": self.required,
        }


_CURRENT_SCHEDULER_TASK: ContextVar[SchedulerTaskBinding | None] = ContextVar(
    "mathforge_current_scheduler_task",
    default=None,
)


def current_scheduler_task_binding() -> SchedulerTaskBinding | None:
    return _CURRENT_SCHEDULER_TASK.get()


@contextmanager
def scheduler_task_context(binding: SchedulerTaskBinding) -> Iterator[None]:
    """Bind one graph node to all provider calls made by its operation."""

    token = _CURRENT_SCHEDULER_TASK.set(binding)
    try:
        yield
    finally:
        _CURRENT_SCHEDULER_TASK.reset(token)
_CLOSURE_ACTIONS = frozenset(
    {
        "candidate_completion",
        "peer_review_response",
        "peer_review",
        "verification",
        "verifier",
        "repair",
        "replan",
        "final_audit",
        "finalization",
        "skill_check",
    }
)


@dataclass(frozen=True)
class TaskNode:
    node_id: str
    role: str
    action: str
    task_id: str
    dependencies: tuple[str, ...] = ()
    priority: int = 0
    expected_p50: float = 0.0
    expected_p95: float = 0.0
    token_cap: int = 0
    closure_value: int = 0
    optional: bool = False
    parallel_group: str = ""
    plan_version: int = 0
    generation: int = 0
    admission: str = "admitted"
    admission_reason: str = ""
    operation: Callable[[], object] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    max_latency: float = 0.0

    def __post_init__(self) -> None:
        if not self.node_id or not self.role or not self.action or not self.task_id:
            raise ValueError("TaskNode identity fields must be non-empty")
        if self.node_id in self.dependencies:
            raise ValueError("TaskNode cannot depend on itself")
        if min(
            self.expected_p50,
            self.expected_p95,
            self.max_latency,
            self.token_cap,
            self.closure_value,
        ) < 0:
            raise ValueError("TaskNode estimates must be nonnegative")
        if self.expected_p50 > self.expected_p95:
            raise ValueError("TaskNode p50 cannot exceed p95")
        if self.max_latency == 0:
            object.__setattr__(self, "max_latency", self.expected_p95)
        elif self.max_latency < self.expected_p95:
            raise ValueError("TaskNode max_latency cannot be below p95")
        if self.plan_version < 0 or self.generation < 0:
            raise ValueError("TaskNode versions must be nonnegative")
        if self.admission not in {"admitted", "rejected", "deferred", "pruned"}:
            raise ValueError("TaskNode admission decision is invalid")

    @property
    def admission_decision(self) -> str:
        """Compatibility alias for the plan-facing admission vocabulary."""

        return self.admission

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["dependencies"] = list(self.dependencies)
        payload.pop("operation", None)
        return payload

    def bind(self, operation: Callable[[], object]) -> "TaskNode":
        if not callable(operation):
            raise TypeError("TaskNode operation must be callable")
        return replace(self, operation=operation)


@dataclass(frozen=True)
class TaskGraph:
    graph_id: str
    nodes: tuple[TaskNode, ...]
    schema_version: str = TASK_GRAPH_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.graph_id or not self.nodes:
            raise ValueError("TaskGraph must have an identity and nodes")
        identifiers = [node.node_id for node in self.nodes]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("TaskGraph node identities must be unique")
        task_ids = [node.task_id for node in self.nodes]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("TaskGraph task identities must be unique")
        known = set(identifiers)
        if any(set(node.dependencies) - known for node in self.nodes):
            raise ValueError("TaskGraph dependency is unknown")
        self._topological_ids()

    def _topological_ids(self) -> tuple[str, ...]:
        remaining = {node.node_id: set(node.dependencies) for node in self.nodes}
        ordered: list[str] = []
        while remaining:
            ready = sorted(node_id for node_id, deps in remaining.items() if not deps)
            if not ready:
                raise ValueError("TaskGraph must be acyclic")
            ordered.extend(ready)
            for node_id in ready:
                remaining.pop(node_id)
            for deps in remaining.values():
                deps.difference_update(ready)
        return tuple(ordered)

    def node(self, node_id: str) -> TaskNode:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        raise KeyError(node_id)

    @property
    def critical_path_p95(self) -> float:
        by_id = {node.node_id: node for node in self.nodes}
        cumulative: dict[str, float] = {}
        for node_id in self._topological_ids():
            node = by_id[node_id]
            cumulative[node_id] = node.expected_p95 + max(
                (cumulative[item] for item in node.dependencies),
                default=0.0,
            )
        return max(cumulative.values(), default=0.0)

    def critical_path_p95_for_workers(self, worker_count: int) -> float:
        """Estimate P95 with the actual bounded worker count."""

        workers = max(1, int(worker_count))
        if workers >= len(self.nodes):
            return self.critical_path_p95
        by_id = {node.node_id: node for node in self.nodes}
        levels: dict[str, int] = {}
        for node_id in self._topological_ids():
            node = by_id[node_id]
            levels[node_id] = 1 + max(
                (levels[item] for item in node.dependencies),
                default=0,
            )
        total = 0.0
        for level in range(1, max(levels.values(), default=0) + 1):
            ready = [node for node in self.nodes if levels[node.node_id] == level]
            loads = [0.0] * workers
            for node in sorted(
                ready,
                key=lambda item: (-item.expected_p95, item.priority, item.node_id),
            ):
                slot = min(range(workers), key=lambda index: loads[index])
                loads[slot] += node.expected_p95
            total += max(loads, default=0.0)
        return total

    def ready_nodes(self, completed: Iterable[str]) -> tuple[TaskNode, ...]:
        completed_ids = set(completed)
        return tuple(
            sorted(
                (
                    node
                    for node in self.nodes
                    if node.node_id not in completed_ids
                    and set(node.dependencies) <= completed_ids
                ),
                key=lambda node: (node.priority, node.node_id),
            )
        )

    def ready_wave(
        self,
        completed: Iterable[str],
        *,
        skipped: Iterable[str] = (),
        running: Iterable[str] = (),
    ) -> tuple[TaskNode, ...]:
        """Return the next executable wave from the graph state."""

        satisfied = set(completed) | set(skipped)
        active = set(running)
        return tuple(
            node
            for node in self.ready_nodes(satisfied)
            if node.node_id not in active
        )

    def ready_waves(
        self,
        completed: Iterable[str],
        *,
        skipped: Iterable[str] = (),
    ) -> tuple[tuple[TaskNode, ...], ...]:
        """Group ready nodes by the declared parallel-group hint."""

        grouped: dict[str, list[TaskNode]] = {}
        for node in self.ready_wave(completed, skipped=skipped):
            grouped.setdefault(node.parallel_group or node.node_id, []).append(node)
        return tuple(
            tuple(sorted(items, key=lambda item: (item.priority, item.node_id)))
            for _, items in sorted(
                grouped.items(),
                key=lambda item: (
                    min(node.priority for node in item[1]),
                    item[0],
                ),
            )
        )

    def bind_operations(
        self,
        operations: Mapping[str, Callable[[], object]],
    ) -> "TaskGraph":
        known = {node.node_id for node in self.nodes}
        unknown = set(operations) - known
        if unknown:
            raise KeyError(f"unknown TaskGraph operations: {sorted(unknown)}")
        return replace(
            self,
            nodes=tuple(
                node.bind(operations[node.node_id])
                if node.node_id in operations
                else node
                for node in self.nodes
            ),
        )

    def pruned(self, node_ids: Iterable[str]) -> "TaskGraph":
        """Remove admitted optional nodes and rewire their dependants."""

        pruned_ids = set(node_ids)
        by_id = {node.node_id: node for node in self.nodes}
        unknown = pruned_ids - set(by_id)
        if unknown:
            raise KeyError(f"unknown TaskGraph nodes: {sorted(unknown)}")
        if any(not by_id[item].optional for item in pruned_ids):
            raise ValueError("only optional TaskGraph nodes may be pruned")
        kept: list[TaskNode] = []
        for node in self.nodes:
            if node.node_id in pruned_ids:
                continue
            dependencies: list[str] = []
            for dependency in node.dependencies:
                if dependency in pruned_ids:
                    dependencies.extend(by_id[dependency].dependencies)
                else:
                    dependencies.append(dependency)
            kept.append(
                replace(node, dependencies=tuple(dict.fromkeys(dependencies)))
            )
        return replace(self, nodes=tuple(kept))

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "graph_id": self.graph_id,
            "critical_path_p95_seconds": round(self.critical_path_p95, 6),
            "nodes": [node.to_dict() for node in self.nodes],
        }


@dataclass(frozen=True)
class ClosureAdmission:
    admitted: bool
    transaction_id: str
    node_ids: tuple[str, ...]
    required_calls: int
    required_seconds: float
    reason: str

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["node_ids"] = list(self.node_ids)
        return payload


@dataclass(frozen=True)
class WaveOutcome:
    task_id: str
    value: object | None
    error: Exception | None
    elapsed_seconds: float
    generation: int = 0
    accepted: bool = True


@dataclass(frozen=True)
class NodeOutcome:
    """A graph-aware result for one dispatched node."""

    node_id: str
    value: object | None = None
    error: Exception | None = None
    elapsed_seconds: float = 0.0
    generation: int = 0
    plan_version: int = 0
    wave_generation: int = 0
    accepted: bool = True

    @property
    def task_id(self) -> str:
        """Keep the wave API usable by existing callers."""

        return self.node_id

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "value": self.value,
            "error_code": type(self.error).__name__ if self.error else "",
            "elapsed_seconds": round(max(0.0, self.elapsed_seconds), 6),
            "generation": self.generation,
            "plan_version": self.plan_version,
            "wave_generation": self.wave_generation,
            "accepted": self.accepted,
        }


@dataclass(frozen=True)
class NodeDispatch:
    """Immutable dispatch identity used by the publish fence."""

    node_id: str
    task_id: str
    generation: int
    plan_version: int
    wave_generation: int
    fence: "PublishFence" = field(repr=False, compare=False)

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "task_id": self.task_id,
            "generation": self.generation,
            "plan_version": self.plan_version,
            "wave_generation": self.wave_generation,
        }


@dataclass(frozen=True)
class GraphExpansion:
    """A deterministic request to append nodes to an active graph."""

    nodes: tuple[TaskNode, ...] = ()
    parent_node_id: str = ""
    action: str = ""
    plan_version: int = 0
    reason: str = ""

    def __post_init__(self) -> None:
        if any(not isinstance(node, TaskNode) for node in self.nodes):
            raise TypeError("GraphExpansion nodes must be TaskNode values")
        if self.plan_version < 0:
            raise ValueError("GraphExpansion plan_version must be nonnegative")

    @classmethod
    def from_action(
        cls,
        action: str,
        nodes: Iterable[TaskNode],
        *,
        parent_node_id: str = "",
        plan_version: int = 0,
        reason: str = "",
    ) -> "GraphExpansion":
        return cls(
            tuple(nodes),
            parent_node_id=parent_node_id,
            action=str(action),
            plan_version=int(plan_version),
            reason=str(reason),
        )

    def to_dict(self) -> dict:
        return {
            "parent_node_id": self.parent_node_id,
            "action": self.action,
            "plan_version": self.plan_version,
            "reason": self.reason,
            "nodes": [node.to_dict() for node in self.nodes],
        }


@dataclass(frozen=True)
class PublishFence:
    """Checks which protect graph state from late or stale model results."""

    session_id: str
    scheduler_task_id: str
    plan_version: int
    generation: int
    wave_generation: int
    cancellation_token: CancellationToken | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    session_active: Callable[[], bool] | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not self.session_id or not self.scheduler_task_id:
            raise ValueError("PublishFence requires session and task identities")
        if min(self.plan_version, self.generation, self.wave_generation) < 0:
            raise ValueError("PublishFence versions must be nonnegative")

    def reason(
        self,
        *,
        active_session_id: str,
        active_plan_version: int,
        task_status: str,
        current_generation: int,
        current_wave_generation: int,
        cancellation_token: CancellationToken | None = None,
    ) -> str:
        """Return a stable rejection reason, or an empty string if valid."""

        if self.session_id != str(active_session_id):
            return "session_inactive"
        if self.session_active is not None and not self.session_active():
            return "session_inactive"
        if self.plan_version != int(active_plan_version):
            return "stale_plan_version"
        if task_status != "running":
            return "task_not_running"
        if self.generation != int(current_generation):
            return "stale_generation"
        if self.wave_generation != int(current_wave_generation):
            return "stale_wave_generation"
        token = cancellation_token or self.cancellation_token
        if token is not None and token.is_cancelled:
            return "cancelled"
        return ""

    def accepts(self, **kwargs) -> bool:
        return not self.reason(**kwargs)

    def validate(self, **kwargs) -> None:
        reason = self.reason(**kwargs)
        if reason:
            raise RuntimeError(f"PublishFence rejected result: {reason}")

    def to_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "scheduler_task_id": self.scheduler_task_id,
            "plan_version": self.plan_version,
            "generation": self.generation,
            "wave_generation": self.wave_generation,
        }


@dataclass(frozen=True)
class NodeExecution:
    node_id: str
    status: str
    generation: int
    elapsed_seconds: float = 0.0
    error_code: str = ""
    plan_version: int = 0
    wave_generation: int = 0
    accepted: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class GraphRunResult:
    values: dict[str, object]
    nodes: tuple[NodeExecution, ...]
    completed: tuple[str, ...]
    skipped: tuple[str, ...]
    failed: tuple[str, ...]
    late_results: tuple[dict, ...] = ()
    dependency_violations: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "values": dict(self.values),
            "nodes": [node.to_dict() for node in self.nodes],
            "completed": list(self.completed),
            "skipped": list(self.skipped),
            "failed": list(self.failed),
            "late_results": [dict(item) for item in self.late_results],
            "dependency_violations": list(self.dependency_violations),
        }


class SchedulerFlow:
    """Deterministic DAG, closure admission, and bounded parallel-wave service."""

    def __init__(self, *, max_workers: int) -> None:
        if max_workers < 1:
            raise ValueError("scheduler worker capacity must be positive")
        self._max_workers = int(max_workers)
        self._generation_lock = Lock()
        self._generations: dict[str, int] = {}

    @property
    def max_workers(self) -> int:
        return self._max_workers

    def issue_generation(self, task_id: str, *, scope: str = "") -> int:
        key = f"{scope}:{task_id}"
        with self._generation_lock:
            token = self._generations.get(key, 0) + 1
            self._generations[key] = token
            return token

    def accepts_generation(
        self,
        task_id: str,
        generation: int,
        *,
        scope: str = "",
    ) -> bool:
        key = f"{scope}:{task_id}"
        with self._generation_lock:
            return self._generations.get(key) == int(generation)

    def invalidate_generation(self, task_id: str, *, scope: str = "") -> int:
        """Fence a timed-out task so a late worker cannot be accepted."""

        return self.issue_generation(task_id, scope=scope)

    def admit_closure(
        self,
        nodes: Iterable[TaskNode],
        *,
        remaining_calls: int,
        remaining_seconds: float,
        maximum_queue_seconds: float,
        finalize_reserve_seconds: float = 0.0,
        model_start_margin_seconds: float = 0.0,
    ) -> ClosureAdmission:
        selected = tuple(nodes)
        node_ids = tuple(node.node_id for node in selected)
        identity = "|".join(
            (
                *node_ids,
                str(int(remaining_calls)),
                f"{max(0.0, float(remaining_seconds)):.6f}",
            )
        )
        transaction_id = f"closure-{sha256(identity.encode('utf-8')).hexdigest()[:16]}"
        required_calls = len(selected)
        required_seconds = stage_sequence_reserve_seconds(
            [node.action for node in selected],
            maximum_queue_seconds,
        )
        if not selected:
            reason = "empty_closure"
        elif any(node.action not in _CLOSURE_ACTIONS for node in selected):
            reason = "speculative_action_in_closure"
        elif len(node_ids) != len(set(node_ids)):
            reason = "duplicate_closure_node"
        elif remaining_calls < required_calls:
            reason = "insufficient_call_capacity"
        elif remaining_seconds < (
            required_seconds
            + max(0.0, float(finalize_reserve_seconds))
            + max(0.0, float(model_start_margin_seconds))
        ):
            reason = "insufficient_time_capacity"
        else:
            reason = "admitted"
        return ClosureAdmission(
            admitted=reason == "admitted",
            transaction_id=transaction_id,
            node_ids=node_ids,
            required_calls=required_calls,
            required_seconds=round(required_seconds, 6),
            reason=reason,
        )

    def prune_infeasible_optional(
        self,
        graph: TaskGraph,
        *,
        remaining_calls: int,
        remaining_seconds: float,
        finalize_reserve_seconds: float = 0.0,
        model_start_margin_seconds: float = 0.0,
    ) -> tuple[TaskGraph, tuple[str, ...]]:
        """Prune the least valuable optional nodes before execution."""

        active = graph
        removed: list[str] = []
        optional = sorted(
            (node for node in active.nodes if node.optional),
            key=lambda node: (node.closure_value, -node.priority, node.node_id),
        )
        while optional and (
            len(active.nodes) > max(1, int(remaining_calls))
            or not self.critical_path_admitted(
                active,
                remaining_seconds=remaining_seconds,
                finalize_reserve_seconds=finalize_reserve_seconds,
                model_start_margin_seconds=model_start_margin_seconds,
            )
        ):
            node = optional.pop(0)
            active = active.pruned((node.node_id,))
            removed.append(node.node_id)
        return active, tuple(removed)

    def critical_path_admitted(
        self,
        graph: TaskGraph,
        *,
        remaining_seconds: float,
        finalize_reserve_seconds: float = 0.0,
        model_start_margin_seconds: float = 0.0,
    ) -> bool:
        """Check P95 plus mandatory reserves against the live time window."""

        required = (
            graph.critical_path_p95_for_workers(self._max_workers)
            + max(0.0, float(finalize_reserve_seconds))
            + max(0.0, float(model_start_margin_seconds))
        )
        return required < max(0.0, float(remaining_seconds))

    def run_parallel(
        self,
        tasks: Iterable[tuple[str, Callable[[], T]]],
        *,
        timeout_seconds: float | None = None,
        generation_scope: str = "",
        preserve_start_order: bool = False,
        cancellation_token: CancellationToken | None = None,
        generation_tokens: Mapping[str, int] | None = None,
        task_bindings: Mapping[str, SchedulerTaskBinding] | None = None,
    ) -> tuple[WaveOutcome, ...]:
        work = tuple(tasks)
        if not work:
            return ()
        if len({task_id for task_id, _ in work}) != len(work):
            raise ValueError("parallel wave task identities must be unique")

        supplied_generations = dict(generation_tokens or {})
        unknown_generations = set(supplied_generations) - {
            task_id for task_id, _ in work
        }
        if unknown_generations:
            raise KeyError(
                "parallel wave generation has unknown tasks: "
                + ", ".join(sorted(unknown_generations))
            )
        supplied_bindings = dict(task_bindings or {})
        unknown_bindings = set(supplied_bindings) - {
            task_id for task_id, _ in work
        }
        if unknown_bindings:
            raise KeyError(
                "parallel wave task binding has unknown tasks: "
                + ", ".join(sorted(unknown_bindings))
            )
        generations: dict[str, int] = {}
        for task_id, _ in work:
            if task_id in supplied_generations:
                generations[task_id] = int(supplied_generations[task_id])
            else:
                generations[task_id] = self.issue_generation(
                    task_id,
                    scope=generation_scope,
                )

        start_events = [Event() for _ in work]
        first_invocation_started = Event()

        def invoke(
            index: int,
            task_id: str,
            operation: Callable[[], T],
        ) -> WaveOutcome:
            # Preserve the first branch's completion-before-alternative
            # contract without serialising all alternatives.  Additional
            # branches remain a bounded parallel wave once branch zero has
            # produced its first result.
            if preserve_start_order and index > 0:
                start_events[0].wait()
            if index == 0:
                first_invocation_started.set()
            if (
                cancellation_token is not None
                and cancellation_token.is_cancelled
            ):
                if preserve_start_order and index == 0:
                    start_events[0].set()
                return WaveOutcome(
                    task_id,
                    None,
                    ModelCallRejected(
                        cancellation_token.reason or "case_cancelled"
                    ),
                    0.0,
                    generations[task_id],
                    False,
                )
            started = perf_counter()
            try:
                binding = supplied_bindings.get(task_id)
                if binding is None:
                    # Keep the legacy bounded-wave entry point safe for model
                    # work as well.  A caller that has not yet adopted the
                    # full GraphExecutor still receives a deterministic task
                    # identity instead of silently entering Provider
                    # unbound.  GraphExecutor supplies the authoritative
                    # binding explicitly and therefore takes precedence.
                    binding = SchedulerTaskBinding(
                        scheduler_task_id=str(task_id),
                        plan_version=0,
                        agent_id="SchedulerFlow",
                        graph_id=str(generation_scope),
                        required=False,
                    )
                with scheduler_task_context(binding):
                    value = operation()
            except Exception as error:
                if preserve_start_order and index == 0:
                    start_events[0].set()
                return WaveOutcome(
                    task_id,
                    None,
                    error,
                    perf_counter() - started,
                    generations[task_id],
                )
            if preserve_start_order and index == 0:
                start_events[0].set()
            return WaveOutcome(
                task_id,
                value,
                None,
                perf_counter() - started,
                generations[task_id],
            )

        wall_started = perf_counter()
        ordered_outcomes: dict[str, WaveOutcome] = {}
        workers = min(self._max_workers, len(work))
        pool = ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="mathforge-runtime-wave",
        )
        future_by_task: dict[str, Future[WaveOutcome]] = {}
        if preserve_start_order:
            first_task_id, first_operation = work[0]
            future_by_task[first_task_id] = pool.submit(
                invoke,
                0,
                first_task_id,
                first_operation,
            )
            # Do not submit the other branches until the deterministic first
            # branch has entered the worker.  They then wait for its first
            # operation to complete before joining the bounded wave; the
            # first branch still runs in the pool, so the timeout is enforced.
            first_invocation_started.wait()
            for index, (task_id, operation) in enumerate(work[1:], start=1):
                future_by_task[task_id] = pool.submit(
                    invoke,
                    index,
                    task_id,
                    operation,
                )
        else:
            future_by_task = {
                task_id: pool.submit(invoke, index, task_id, operation)
                for index, (task_id, operation) in enumerate(work)
            }
        pending = set(future_by_task.values())
        timed_out = False
        cancelled = bool(
            cancellation_token is not None
            and cancellation_token.is_cancelled
        )
        try:
            while pending and not timed_out and not cancelled:
                elapsed = perf_counter() - wall_started
                remaining = (
                    None
                    if timeout_seconds is None
                    else max(0.0, float(timeout_seconds) - elapsed)
                )
                if remaining is not None and remaining <= 0:
                    timed_out = True
                    break
                completed, pending = wait(
                    pending,
                    timeout=(
                        0.05
                        if remaining is None
                        else min(0.05, remaining)
                    ),
                    return_when=ALL_COMPLETED,
                )
                for future in completed:
                    outcome = future.result()
                    ordered_outcomes[outcome.task_id] = replace(
                        outcome,
                        accepted=self.accepts_generation(
                            outcome.task_id,
                            outcome.generation,
                            scope=generation_scope,
                        ),
                    )
                cancelled = bool(
                    cancellation_token is not None
                    and cancellation_token.is_cancelled
                )
            if pending:
                reason = (
                    cancellation_token.reason
                    if cancelled and cancellation_token is not None
                    else "parallel wave deadline reached"
                )
                if not cancelled:
                    timed_out = True
                    if cancellation_token is not None:
                        cancellation_token.cancel("scheduler_wave_timeout")
                for task_id, future in future_by_task.items():
                    if future not in pending:
                        continue
                    self.invalidate_generation(task_id, scope=generation_scope)
                    future.cancel()
                    ordered_outcomes[task_id] = WaveOutcome(
                        task_id,
                        None,
                        (
                            ModelCallRejected(reason)
                            if cancelled
                            else TimeoutError(reason)
                        ),
                        max(0.0, perf_counter() - wall_started),
                        generations[task_id],
                        False,
                    )
        finally:
            # The executor is never allowed to own a reference to a case
            # longer than the wave.  Running provider work is fenced and may
            # finish in its own provider tail, but no scheduler future is
            # retained by this flow.
            pool.shutdown(wait=False, cancel_futures=True)
        return tuple(
            ordered_outcomes.get(
                task_id,
                WaveOutcome(
                    task_id,
                    None,
                    TimeoutError("parallel wave deadline reached"),
                    max(0.0, float(timeout_seconds or 0.0)),
                    generations[task_id],
                ),
            )
            for task_id, _ in work
        )

    def run_graph(
        self,
        graph: TaskGraph,
        *,
        initial_completed: Iterable[str] = (),
        prune_optional: Iterable[str] = (),
        timeout_seconds: float | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> GraphRunResult:
        """Execute bound graph operations wave-by-wave.

        Node transitions are committed only when the generation token issued
        for that node is still current.  A timed-out worker can therefore
        finish in the background without overwriting a newer graph state.
        """

        pruned = set(prune_optional)
        graph = graph.pruned(pruned) if pruned else graph
        completed = set(initial_completed)
        skipped = set(pruned)
        failed: set[str] = set()
        values: dict[str, object] = {}
        executions: dict[str, NodeExecution] = {
            node_id: NodeExecution(node_id, "pending", 0)
            for node_id in (
                [node.node_id for node in graph.nodes] + sorted(pruned)
            )
        }
        if completed - {node.node_id for node in graph.nodes}:
            raise KeyError("initial_completed contains an unknown TaskGraph node")
        started_at = perf_counter()

        while True:
            wave = graph.ready_wave(completed, skipped=skipped)
            if not wave:
                break
            tasks: list[tuple[str, Callable[[], object]]] = []
            for node in wave:
                if node.node_id in completed or node.node_id in skipped:
                    continue
                if node.operation is None:
                    error = TypeError(
                        f"TaskGraph node {node.node_id!r} has no bound operation"
                    )
                    failed.add(node.node_id)
                    executions[node.node_id] = NodeExecution(
                        node.node_id,
                        "failed",
                        0,
                        error_code=type(error).__name__,
                    )
                    continue
                executions[node.node_id] = NodeExecution(
                    node.node_id,
                    "running",
                    0,
                )
                tasks.append((node.node_id, node.operation))
            if not tasks:
                break
            remaining = None
            if timeout_seconds is not None:
                remaining = max(0.0, float(timeout_seconds) - (perf_counter() - started_at))
            outcomes = self.run_parallel(
                tasks,
                timeout_seconds=remaining,
                generation_scope=graph.graph_id,
                cancellation_token=cancellation_token,
            )
            for outcome in outcomes:
                if not outcome.accepted:
                    executions[outcome.task_id] = NodeExecution(
                        outcome.task_id,
                        "stale",
                        outcome.generation,
                        outcome.elapsed_seconds,
                        "stale_generation",
                    )
                    failed.add(outcome.task_id)
                    continue
                if outcome.error is None:
                    completed.add(outcome.task_id)
                    values[outcome.task_id] = outcome.value
                    executions[outcome.task_id] = NodeExecution(
                        outcome.task_id,
                        "completed",
                        outcome.generation,
                        outcome.elapsed_seconds,
                    )
                else:
                    failed.add(outcome.task_id)
                    executions[outcome.task_id] = NodeExecution(
                        outcome.task_id,
                        "failed",
                        outcome.generation,
                        outcome.elapsed_seconds,
                        type(outcome.error).__name__,
                    )
            # A failed required node blocks the graph; optional descendants are
            # explicitly skipped so the terminal state stays finite and clear.
            failed_ids = set(failed)
            for node in graph.nodes:
                if node.node_id in completed or node.node_id in skipped:
                    continue
                if set(node.dependencies) & failed_ids:
                    if node.optional:
                        skipped.add(node.node_id)
                        executions[node.node_id] = NodeExecution(
                            node.node_id,
                            "skipped",
                            0,
                            error_code="dependency_failed",
                        )
                    elif not node.dependencies <= completed:
                        failed.add(node.node_id)
                        executions[node.node_id] = NodeExecution(
                            node.node_id,
                            "blocked",
                            0,
                            error_code="dependency_failed",
                        )
        for node_id in skipped:
            executions.setdefault(
                node_id,
                NodeExecution(node_id, "skipped", 0),
            )
        return GraphRunResult(
            values=values,
            nodes=tuple(
                executions[node.node_id]
                for node in graph.nodes
            ) + tuple(
                executions[node_id]
                for node_id in sorted(pruned)
                if node_id not in {node.node_id for node in graph.nodes}
            ),
            completed=tuple(sorted(completed)),
            skipped=tuple(sorted(skipped)),
            failed=tuple(sorted(failed)),
        )


@dataclass
class GraphState:
    """Mutable per-session state owned by :class:`GraphExecutor`."""

    graph: TaskGraph
    session_id: str = "graph-session"
    plan_version: int = 0
    cancellation_token: CancellationToken | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    active: bool = True
    statuses: dict[str, str] = field(default_factory=dict)
    generations: dict[str, int] = field(default_factory=dict)
    wave_generations: dict[str, int] = field(default_factory=dict)
    values: dict[str, object] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    executions: dict[str, NodeExecution] = field(default_factory=dict)
    late_results: list[dict] = field(default_factory=list)
    dependency_violations: list[str] = field(default_factory=list)
    _wave_generation: int = 0

    def __post_init__(self) -> None:
        if not self.session_id:
            raise ValueError("GraphState session_id must be non-empty")
        if self.plan_version < 0:
            raise ValueError("GraphState plan_version must be nonnegative")
        if self.cancellation_token is None:
            self.cancellation_token = CancellationToken()
        for node in self.graph.nodes:
            self.statuses.setdefault(
                node.node_id,
                "skipped" if node.admission != "admitted" else "pending",
            )
            self.executions.setdefault(
                node.node_id,
                NodeExecution(
                    node.node_id,
                    self.statuses[node.node_id],
                    node.generation,
                    plan_version=node.plan_version or self.plan_version,
                    accepted=node.admission == "admitted",
                ),
            )

    @property
    def wave_generation(self) -> int:
        return self._wave_generation

    def next_wave_generation(self) -> int:
        self._wave_generation += 1
        return self._wave_generation

    def terminal(self, node_id: str) -> bool:
        return self.statuses.get(node_id) in (
            GRAPH_TERMINAL_STATES - {"pending", "ready", "running"}
        )

    def snapshot(self) -> dict:
        return {
            "session_id": self.session_id,
            "plan_version": self.plan_version,
            "active": self.active,
            "wave_generation": self.wave_generation,
            "statuses": dict(self.statuses),
            "generations": dict(self.generations),
            "values": dict(self.values),
            "errors": dict(self.errors),
            "late_results": [dict(item) for item in self.late_results],
            "dependency_violations": list(self.dependency_violations),
        }


class GraphExecutor:
    """Authoritative graph scheduler with explicit dispatch/commit fences.

    ``SchedulerFlow`` remains the bounded worker implementation.  This class
    owns which nodes may run, when a result can publish, and how expansions or
    replans alter the graph.  Keeping those concerns here prevents a legacy
    parallel helper from silently becoming a second execution authority.
    """

    def __init__(
        self,
        graph: TaskGraph,
        *,
        scheduler: SchedulerFlow | None = None,
        max_workers: int | None = None,
        worker_count: int | None = None,
        session_id: str = "graph-session",
        plan_version: int = 0,
        cancellation_token: CancellationToken | None = None,
        session_active: Callable[[], bool] | None = None,
        initial_completed: Iterable[str] = (),
        prune_optional: Iterable[str] = (),
    ) -> None:
        if scheduler is None:
            configured_workers = (
                worker_count
                if worker_count is not None
                else max_workers
                if max_workers is not None
                else 1
            )
            scheduler = SchedulerFlow(max_workers=int(configured_workers))
        elif max_workers is not None or worker_count is not None:
            requested = int(worker_count if worker_count is not None else max_workers)
            if requested != scheduler.max_workers:
                raise ValueError("GraphExecutor worker count conflicts with SchedulerFlow")
        pruned = set(prune_optional)
        self._pruned = tuple(sorted(pruned))
        self._scheduler = scheduler
        self._session_active = session_active
        self._bindings: dict[str, SchedulerTaskBinding] = {}
        active_graph = graph.pruned(pruned) if pruned else graph
        configured_plan_version = int(plan_version)
        if configured_plan_version == 0:
            configured_plan_version = max(
                (node.plan_version for node in active_graph.nodes),
                default=0,
            )
        if configured_plan_version:
            active_graph = replace(
                active_graph,
                nodes=tuple(
                    replace(node, plan_version=configured_plan_version)
                    if node.plan_version == 0
                    else node
                    for node in active_graph.nodes
                ),
            )
        self._state = GraphState(
            active_graph,
            session_id=str(session_id),
            plan_version=configured_plan_version,
            cancellation_token=cancellation_token,
        )
        self._lock = Lock()
        unknown_completed = set(initial_completed) - {
            node.node_id for node in active_graph.nodes
        }
        if unknown_completed:
            raise KeyError(
                "initial_completed contains unknown graph nodes: "
                + ", ".join(sorted(unknown_completed))
            )
        for node_id in initial_completed:
            self._state.statuses[node_id] = "completed"
            self._state.executions[node_id] = NodeExecution(
                node_id,
                "completed",
                self._state.generations.get(node_id, 0),
                plan_version=self._node_plan_version(node_id),
            )
        for node_id in self._pruned:
            self._state.statuses[node_id] = "skipped"
            self._state.executions[node_id] = NodeExecution(
                node_id,
                "skipped",
                0,
                error_code="pruned",
                plan_version=self._state.plan_version,
                accepted=False,
            )

    @property
    def graph(self) -> TaskGraph:
        return self._state.graph

    @property
    def state(self) -> GraphState:
        return self._state

    @property
    def scheduler(self) -> SchedulerFlow:
        return self._scheduler

    @property
    def max_workers(self) -> int:
        return self._scheduler.max_workers

    @property
    def active_plan_version(self) -> int:
        return self._state.plan_version

    def node_status(self, node_id: str) -> str:
        with self._lock:
            self._require_node(node_id)
            return self._state.statuses[node_id]

    def execution(self, node_id: str) -> NodeExecution:
        """Return the authoritative terminal/running record for a node."""

        with self._lock:
            self._require_node(node_id)
            return self._state.executions[node_id]

    def can_start_speculative(
        self,
        *,
        remaining_seconds: float,
        finalize_reserve_seconds: float = 0.0,
        model_start_margin_seconds: float = 0.0,
    ) -> bool:
        """Use the live remaining window before admitting speculative work.

        Completed ancestors no longer consume the remaining model window, so
        the admission path is calculated over the unresolved graph frontier.
        """

        with self._lock:
            completed = {
                node_id
                for node_id, status in self._state.statuses.items()
                if status == "completed"
            }
            unresolved = [
                node
                for node in self._state.graph.nodes
                if self._state.statuses.get(node.node_id)
                not in {
                    "completed",
                    "skipped",
                    "cancelled",
                    "failed",
                    "blocked",
                    "stale",
                }
            ]
            if not unresolved:
                return True
            unresolved_ids = {node.node_id for node in unresolved}
            frontier = tuple(
                replace(
                    node,
                    dependencies=tuple(
                        dependency
                        for dependency in node.dependencies
                        if dependency in unresolved_ids and dependency not in completed
                    ),
                )
                for node in unresolved
            )
            graph = TaskGraph(
                self._state.graph.graph_id,
                frontier,
                schema_version=self._state.graph.schema_version,
            )
        return self._scheduler.critical_path_admitted(
            graph,
            remaining_seconds=remaining_seconds,
            finalize_reserve_seconds=finalize_reserve_seconds,
            model_start_margin_seconds=model_start_margin_seconds,
        )

    def ready(
        self,
        *,
        parallel_group: str | None = None,
        actions: Iterable[str] | None = None,
        limit: int | None = None,
    ) -> tuple[TaskNode, ...]:
        """Return only admissible pending nodes whose dependencies completed."""

        with self._lock:
            completed = {
                node_id
                for node_id, status in self._state.statuses.items()
                if status == "completed"
            }
            ready = []
            allowed_actions = set(actions) if actions is not None else None
            for node in self._state.graph.ready_nodes(completed):
                if self._state.statuses.get(node.node_id) != "pending":
                    continue
                if node.admission != "admitted":
                    continue
                if parallel_group is not None and node.parallel_group != parallel_group:
                    continue
                if allowed_actions is not None and node.action not in allowed_actions:
                    continue
                ready.append(node)
            if limit is not None:
                ready = ready[: max(0, int(limit))]
            for node in ready:
                self._state.statuses[node.node_id] = "ready"
                self._state.executions[node.node_id] = replace(
                    self._state.executions[node.node_id],
                    status="ready",
                    plan_version=self._node_plan_version(node.node_id),
                )
            return tuple(ready)

    def _ready_or_requested(
        self,
        nodes: Iterable[str | TaskNode] | None,
    ) -> tuple[TaskNode, ...]:
        if nodes is None:
            return self.ready()
        selected: list[TaskNode] = []
        for item in nodes:
            node_id = item.node_id if isinstance(item, TaskNode) else str(item)
            self._require_node(node_id)
            node = self._state.graph.node(node_id)
            if self._state.statuses.get(node_id) not in {"pending", "ready"}:
                continue
            if node.admission != "admitted":
                self._state.statuses[node_id] = "skipped"
                continue
            dependencies = set(node.dependencies)
            if not dependencies <= {
                dependency
                for dependency, status in self._state.statuses.items()
                if status == "completed"
            }:
                self._state.dependency_violations.append(node_id)
                raise RuntimeError(
                    f"TaskGraph dependency violation for node {node_id!r}"
                )
            selected.append(node)
        return tuple(selected)

    def dispatch(
        self,
        nodes: Iterable[str | TaskNode] | None = None,
        operation: Callable[[], object] | Mapping[str, Callable[[], object]] | None = None,
        *,
        operations: Mapping[str, Callable[[], object]] | None = None,
        plan_version: int | None = None,
    ) -> tuple[NodeDispatch, ...]:
        """Admit and mark a ready wave as running, issuing unique generations."""

        requested_version = (
            self._state.plan_version if plan_version is None else int(plan_version)
        )
        if requested_version != self._state.plan_version:
            raise RuntimeError("dispatch plan_version is not active")
        with self._lock:
            if not self._state.active:
                raise RuntimeError("GraphExecutor is inactive")
            if self._state.cancellation_token.is_cancelled:
                raise RuntimeError("GraphExecutor cancellation requested")
            selected = self._ready_or_requested(nodes)
            if operation is not None:
                if operations is not None:
                    raise TypeError("dispatch accepts operation or operations, not both")
                if callable(operation):
                    if len(selected) != 1:
                        raise ValueError(
                            "a single callable operation requires one dispatched node"
                        )
                    operations = {selected[0].node_id: operation}
                else:
                    operations = operation
            if operations:
                unknown = set(operations) - {node.node_id for node in selected}
                if unknown:
                    raise KeyError(
                        "dispatch operations target non-dispatched nodes: "
                        + ", ".join(sorted(unknown))
                    )
                self._state.graph = self._state.graph.bind_operations(operations)
                selected = tuple(self._state.graph.node(node.node_id) for node in selected)
            wave_generation = self._state.next_wave_generation()
            dispatches: list[NodeDispatch] = []
            for node in selected:
                generation = self._scheduler.issue_generation(
                    node.node_id,
                    scope=self._state.graph.graph_id,
                )
                self._state.generations[node.node_id] = generation
                self._state.wave_generations[node.node_id] = wave_generation
                self._state.statuses[node.node_id] = "running"
                node_plan_version = self._node_plan_version(node.node_id)
                if node_plan_version != self._state.plan_version:
                    self._state.statuses[node.node_id] = "cancelled"
                    self._state.errors[node.node_id] = "stale_plan_version"
                    self._state.executions[node.node_id] = NodeExecution(
                        node.node_id,
                        "cancelled",
                        generation,
                        error_code="stale_plan_version",
                        plan_version=node_plan_version,
                        wave_generation=wave_generation,
                        accepted=False,
                    )
                    continue
                binding = SchedulerTaskBinding(
                    scheduler_task_id=node.task_id,
                    plan_version=node_plan_version,
                    agent_id=node.role,
                    wave_generation=wave_generation,
                    graph_id=self._state.graph.graph_id,
                )
                fence = PublishFence(
                    self._state.session_id,
                    node.task_id,
                    node_plan_version,
                    generation,
                    wave_generation,
                    self._state.cancellation_token,
                    self._session_active,
                )
                self._state.executions[node.node_id] = NodeExecution(
                    node.node_id,
                    "running",
                    generation,
                    plan_version=node_plan_version,
                    wave_generation=wave_generation,
                )
                dispatches.append(
                    NodeDispatch(
                        node.node_id,
                        node.task_id,
                        generation,
                        node_plan_version,
                        wave_generation,
                        fence,
                    )
                )
                # The binding is attached to the operation at run time via
                # ``_binding_for``; retaining it here keeps dispatch pure.
                self._bindings[node.node_id] = binding
            return tuple(dispatches)

    def _binding_for(self, node_id: str) -> SchedulerTaskBinding:
        return self._bindings[node_id]

    def run_dispatched(
        self,
        dispatches: Iterable[NodeDispatch],
        *,
        timeout_seconds: float | None = None,
        preserve_start_order: bool = False,
    ) -> tuple[NodeOutcome, ...]:
        dispatches = tuple(dispatches)
        tasks: list[tuple[str, Callable[[], object]]] = []
        tokens: dict[str, int] = {}
        bindings: dict[str, SchedulerTaskBinding] = {}
        immediate: dict[str, NodeOutcome] = {}
        for dispatch in dispatches:
            node = self._state.graph.node(dispatch.node_id)
            if node.operation is None:
                error = TypeError(
                    f"TaskGraph node {node.node_id!r} has no bound operation"
                )
                outcome = NodeOutcome(
                    node.node_id,
                    error=error,
                    generation=dispatch.generation,
                    plan_version=dispatch.plan_version,
                    wave_generation=dispatch.wave_generation,
                    accepted=True,
                )
                self.commit(outcome, fence=dispatch.fence)
                immediate[node.node_id] = outcome
                continue
            tasks.append((node.node_id, node.operation))
            tokens[node.node_id] = dispatch.generation
            bindings[node.node_id] = self._binding_for(node.node_id)
        if not tasks:
            return tuple(immediate[dispatch.node_id] for dispatch in dispatches)
        outcomes = self._scheduler.run_parallel(
            tasks,
            timeout_seconds=timeout_seconds,
            generation_scope=self._state.graph.graph_id,
            preserve_start_order=preserve_start_order,
            cancellation_token=self._state.cancellation_token,
            generation_tokens=tokens,
            task_bindings=bindings,
        )
        by_id = {dispatch.node_id: dispatch for dispatch in dispatches}
        converted: dict[str, NodeOutcome] = dict(immediate)
        for outcome in outcomes:
            dispatch = by_id[outcome.task_id]
            converted_outcome = NodeOutcome(
                outcome.task_id,
                outcome.value,
                outcome.error,
                outcome.elapsed_seconds,
                outcome.generation,
                dispatch.plan_version,
                dispatch.wave_generation,
                outcome.accepted,
            )
            self.commit(converted_outcome, fence=dispatch.fence)
            converted[outcome.task_id] = converted_outcome
        return tuple(converted[dispatch.node_id] for dispatch in dispatches)

    def run_wave(
        self,
        nodes: Iterable[str | TaskNode] | None = None,
        *,
        operations: Mapping[str, Callable[[], object]] | None = None,
        timeout_seconds: float | None = None,
        preserve_start_order: bool = False,
        plan_version: int | None = None,
    ) -> tuple[NodeOutcome, ...]:
        dispatches = self.dispatch(
            nodes,
            operations=operations,
            plan_version=plan_version,
        )
        return self.run_dispatched(
            dispatches,
            timeout_seconds=timeout_seconds,
            preserve_start_order=preserve_start_order,
        )

    def commit(
        self,
        outcome: NodeOutcome | WaveOutcome,
        *,
        fence: PublishFence | None = None,
    ) -> bool:
        """Commit only a result that still passes every publish fence."""

        node_id = outcome.node_id if isinstance(outcome, NodeOutcome) else outcome.task_id
        with self._lock:
            self._require_node(node_id)
            dispatch_generation = int(outcome.generation)
            expected_generation = self._state.generations.get(node_id, 0)
            expected_wave = self._state.wave_generations.get(node_id, 0)
            plan_version = (
                int(outcome.plan_version)
                if isinstance(outcome, NodeOutcome)
                else self._node_plan_version(node_id)
            )
            wave_generation = (
                int(outcome.wave_generation)
                if isinstance(outcome, NodeOutcome)
                else expected_wave
            )
            active = self._session_active is None or bool(self._session_active())
            reason = ""
            if fence is not None:
                expected_task_id = self._state.graph.node(node_id).task_id
                if fence.scheduler_task_id != expected_task_id:
                    reason = "task_identity_mismatch"
                elif dispatch_generation != fence.generation:
                    reason = "stale_generation"
                elif plan_version != fence.plan_version:
                    reason = "stale_plan_version"
                elif wave_generation != fence.wave_generation:
                    reason = "stale_wave_generation"
                else:
                    reason = fence.reason(
                        active_session_id=self._state.session_id,
                        active_plan_version=self._state.plan_version,
                        task_status=self._state.statuses.get(node_id, ""),
                        current_generation=expected_generation,
                        current_wave_generation=expected_wave,
                        cancellation_token=self._state.cancellation_token,
                    )
            elif not active:
                reason = "session_inactive"
            elif self._state.statuses.get(node_id) != "running":
                reason = "task_not_running"
            elif dispatch_generation != expected_generation:
                reason = "stale_generation"
            elif plan_version != self._state.plan_version:
                reason = "stale_plan_version"
            elif wave_generation != expected_wave:
                reason = "stale_wave_generation"
            elif self._state.cancellation_token.is_cancelled:
                reason = "cancelled"
            if not bool(getattr(outcome, "accepted", True)):
                reason = reason or "stale_generation"
            if reason:
                self._record_late_result(node_id, outcome, reason)
                # A newer generation may already be running; do not overwrite
                # that state.  If this was the active generation, mark it
                # cancelled so descendants can never consume the value.
                if self._state.statuses.get(node_id) == "running" and (
                    dispatch_generation == expected_generation
                ):
                    self._state.statuses[node_id] = "cancelled"
                    self._state.executions[node_id] = NodeExecution(
                        node_id,
                        "cancelled",
                        dispatch_generation,
                        getattr(outcome, "elapsed_seconds", 0.0),
                        reason,
                        plan_version,
                        wave_generation,
                        False,
                    )
                return False
            error = outcome.error
            if error is None:
                self._state.statuses[node_id] = "completed"
                self._state.values[node_id] = outcome.value
                status = "completed"
                error_code = ""
            else:
                self._state.statuses[node_id] = "failed"
                error_code = type(error).__name__
                self._state.errors[node_id] = error_code
                status = "failed"
            self._state.executions[node_id] = NodeExecution(
                node_id,
                status,
                dispatch_generation,
                getattr(outcome, "elapsed_seconds", 0.0),
                error_code,
                plan_version,
                wave_generation,
                True,
            )
            return True

    def _record_late_result(
        self,
        node_id: str,
        outcome: NodeOutcome | WaveOutcome,
        reason: str,
    ) -> None:
        self._state.late_results.append(
            {
                "node_id": node_id,
                "generation": int(getattr(outcome, "generation", 0)),
                "plan_version": int(getattr(outcome, "plan_version", 0)),
                "wave_generation": int(getattr(outcome, "wave_generation", 0)),
                "reason": reason,
                "error_code": (
                    type(outcome.error).__name__ if outcome.error else ""
                ),
            }
        )

    def expand(
        self,
        expansion: GraphExpansion | Iterable[TaskNode],
        *,
        plan_version: int | None = None,
    ) -> tuple[TaskNode, ...]:
        """Append a validated dynamic graph expansion without a side path."""

        if isinstance(expansion, GraphExpansion):
            request = expansion
        else:
            request = GraphExpansion(tuple(expansion))
        requested_version = request.plan_version or self._state.plan_version
        if plan_version is not None:
            requested_version = int(plan_version)
        if requested_version != self._state.plan_version:
            raise RuntimeError("GraphExpansion plan_version is stale")
        with self._lock:
            if not self._state.active:
                raise RuntimeError("GraphExecutor is inactive")
            if self._state.cancellation_token.is_cancelled:
                raise RuntimeError("GraphExecutor cancellation requested")
            existing = {node.node_id for node in self._state.graph.nodes}
            duplicate = existing.intersection(node.node_id for node in request.nodes)
            if duplicate:
                raise ValueError(
                    "GraphExpansion node identities already exist: "
                    + ", ".join(sorted(duplicate))
                )
            if request.parent_node_id and request.parent_node_id not in existing:
                raise KeyError(request.parent_node_id)
            nodes = list(request.nodes)
            existing_task_ids = {
                node.task_id for node in self._state.graph.nodes
            }
            duplicate_tasks = existing_task_ids.intersection(
                node.task_id for node in nodes
            )
            if duplicate_tasks:
                raise ValueError(
                    "GraphExpansion task identities already exist: "
                    + ", ".join(sorted(duplicate_tasks))
                )
            task_ids = [node.task_id for node in nodes]
            if len(task_ids) != len(set(task_ids)):
                raise ValueError("GraphExpansion task identities must be unique")
            known = existing | {node.node_id for node in nodes}
            if any(set(node.dependencies) - known for node in nodes):
                raise ValueError("GraphExpansion contains unknown dependencies")
            for node in nodes:
                if node.plan_version not in {0, self._state.plan_version}:
                    raise RuntimeError("GraphExpansion node has stale plan_version")
            if request.parent_node_id:
                nodes = [
                    node
                    if request.parent_node_id in node.dependencies
                    else replace(
                        node,
                        dependencies=(*node.dependencies, request.parent_node_id),
                    )
                    for node in nodes
                ]
            self._state.graph = replace(
                self._state.graph,
                nodes=(*self._state.graph.nodes, *nodes),
            )
            for node in nodes:
                self._state.statuses[node.node_id] = (
                    "skipped" if node.admission != "admitted" else "pending"
                )
                self._state.executions[node.node_id] = NodeExecution(
                    node.node_id,
                    self._state.statuses[node.node_id],
                    node.generation,
                    plan_version=self._node_plan_version(node.node_id),
                    accepted=node.admission == "admitted",
                )
            return tuple(nodes)

    def cancel_plan_version(
        self,
        plan_version: int,
        *,
        reason: str = "plan_version_cancelled",
    ) -> tuple[str, ...]:
        """Advance the active plan and fence all incompatible work."""

        target = int(plan_version)
        if target < 0:
            raise ValueError("plan_version must be nonnegative")
        with self._lock:
            if target < self._state.plan_version:
                raise ValueError("plan_version cannot move backwards")
            cancelled: list[str] = []
            self._state.plan_version = target
            for node in self._state.graph.nodes:
                node_version = node.plan_version or target
                if node_version == target:
                    continue
                if self._state.statuses.get(node.node_id) in {
                    "pending",
                    "ready",
                    "running",
                }:
                    self._scheduler.invalidate_generation(
                        node.node_id,
                        scope=self._state.graph.graph_id,
                    )
                    self._state.statuses[node.node_id] = "cancelled"
                    self._state.errors[node.node_id] = str(reason)
                    self._state.executions[node.node_id] = NodeExecution(
                        node.node_id,
                        "cancelled",
                        self._state.generations.get(node.node_id, 0),
                        error_code=str(reason),
                        plan_version=node_version,
                        accepted=False,
                    )
                    cancelled.append(node.node_id)
            return tuple(cancelled)

    def cancel(self, reason: str = "graph_cancelled") -> tuple[str, ...]:
        with self._lock:
            self._state.active = False
            if not self._state.cancellation_token.is_cancelled:
                self._state.cancellation_token.cancel(str(reason))
            cancelled = []
            for node in self._state.graph.nodes:
                if self._state.statuses.get(node.node_id) in {
                    "pending",
                    "ready",
                    "running",
                }:
                    self._scheduler.invalidate_generation(
                        node.node_id,
                        scope=self._state.graph.graph_id,
                    )
                    self._state.statuses[node.node_id] = "cancelled"
                    self._state.errors[node.node_id] = str(reason)
                    self._state.executions[node.node_id] = NodeExecution(
                        node.node_id,
                        "cancelled",
                        self._state.generations.get(node.node_id, 0),
                        error_code=str(reason),
                        plan_version=self._node_plan_version(node.node_id),
                        wave_generation=self._state.wave_generations.get(
                            node.node_id,
                            0,
                        ),
                        accepted=False,
                    )
                    cancelled.append(node.node_id)
            return tuple(cancelled)

    def _node_plan_version(self, node_id: str) -> int:
        node = self._state.graph.node(node_id)
        return node.plan_version or self._state.plan_version

    def _require_node(self, node_id: str) -> None:
        if node_id not in {node.node_id for node in self._state.graph.nodes}:
            raise KeyError(node_id)

    def result(self) -> GraphRunResult:
        with self._lock:
            completed = tuple(
                sorted(
                    node_id
                    for node_id, status in self._state.statuses.items()
                    if status == "completed"
                )
            )
            skipped = tuple(
                sorted(
                    node_id
                    for node_id, status in self._state.statuses.items()
                    if status in {"skipped", "cancelled", "blocked"}
                )
            )
            failed = tuple(
                sorted(
                    node_id
                    for node_id, status in self._state.statuses.items()
                    if status in {"failed", "stale"}
                )
            )
            return GraphRunResult(
                values=dict(self._state.values),
                nodes=tuple(
                    self._state.executions[node.node_id]
                    for node in self._state.graph.nodes
                )
                + tuple(
                    self._state.executions[node_id]
                    for node_id in self._pruned
                    if node_id in self._state.executions
                ),
                completed=completed,
                skipped=skipped,
                failed=failed,
                late_results=tuple(dict(item) for item in self._state.late_results),
                dependency_violations=tuple(self._state.dependency_violations),
            )

    def run_until_idle(
        self,
        *,
        timeout_seconds: float | None = None,
    ) -> GraphRunResult:
        started = perf_counter()
        while True:
            ready = self.ready()
            if not ready:
                break
            remaining = None
            if timeout_seconds is not None:
                remaining = max(0.0, float(timeout_seconds) - (perf_counter() - started))
            self.run_wave(ready, timeout_seconds=remaining)
            self._mark_blocked_descendants()
        self.finalize_pending()
        return self.result()

    execute = run_until_idle

    def _mark_blocked_descendants(self) -> None:
        with self._lock:
            completed = {
                node_id
                for node_id, status in self._state.statuses.items()
                if status == "completed"
            }
            failed = {
                node_id
                for node_id, status in self._state.statuses.items()
                if status in {"failed", "cancelled", "stale", "blocked"}
            }
            for node in self._state.graph.nodes:
                if self._state.statuses.get(node.node_id) not in {
                    "pending",
                    "ready",
                }:
                    continue
                if set(node.dependencies) & failed:
                    target = "skipped" if node.optional else "failed"
                    self._state.statuses[node.node_id] = target
                    self._state.errors[node.node_id] = "dependency_failed"
                    self._state.executions[node.node_id] = NodeExecution(
                        node.node_id,
                        target,
                        self._state.generations.get(node.node_id, 0),
                        error_code="dependency_failed",
                        plan_version=self._node_plan_version(node.node_id),
                        accepted=False,
                    )
                elif set(node.dependencies) <= completed:
                    continue
                elif all(self._state.terminal(dep) for dep in node.dependencies):
                    self._state.dependency_violations.append(node.node_id)

    def finalize_pending(
        self,
        reason: str = "not_admitted_by_execution_plan",
    ) -> tuple[str, ...]:
        """Close nodes that were intentionally left outside executed waves."""

        with self._lock:
            finalized: list[str] = []
            for node in self._state.graph.nodes:
                if self._state.statuses.get(node.node_id) not in {"pending", "ready"}:
                    continue
                self._state.statuses[node.node_id] = "skipped"
                self._state.errors[node.node_id] = str(reason)
                self._state.executions[node.node_id] = NodeExecution(
                    node.node_id,
                    "skipped",
                    self._state.generations.get(node.node_id, 0),
                    error_code=str(reason),
                    plan_version=self._node_plan_version(node.node_id),
                    wave_generation=self._state.wave_generations.get(node.node_id, 0),
                    accepted=False,
                )
                finalized.append(node.node_id)
            return tuple(finalized)

    def snapshot(self) -> dict:
        return self._state.snapshot()
