from __future__ import annotations

from concurrent.futures import ALL_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass, field, replace
from hashlib import sha256
from threading import Lock
from time import perf_counter
from typing import Callable, Iterable, Mapping, TypeVar

from mathforge.harness.model_policy import stage_sequence_reserve_seconds


T = TypeVar("T")
TASK_GRAPH_SCHEMA_VERSION = "1.0"
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
    operation: Callable[[], object] | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not self.node_id or not self.role or not self.action or not self.task_id:
            raise ValueError("TaskNode identity fields must be non-empty")
        if self.node_id in self.dependencies:
            raise ValueError("TaskNode cannot depend on itself")
        if min(self.expected_p50, self.expected_p95, self.token_cap, self.closure_value) < 0:
            raise ValueError("TaskNode estimates must be nonnegative")
        if self.expected_p50 > self.expected_p95:
            raise ValueError("TaskNode p50 cannot exceed p95")

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
class NodeExecution:
    node_id: str
    status: str
    generation: int
    elapsed_seconds: float = 0.0
    error_code: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class GraphRunResult:
    values: dict[str, object]
    nodes: tuple[NodeExecution, ...]
    completed: tuple[str, ...]
    skipped: tuple[str, ...]
    failed: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "values": dict(self.values),
            "nodes": [node.to_dict() for node in self.nodes],
            "completed": list(self.completed),
            "skipped": list(self.skipped),
            "failed": list(self.failed),
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

    def admit_closure(
        self,
        nodes: Iterable[TaskNode],
        *,
        remaining_calls: int,
        remaining_seconds: float,
        maximum_queue_seconds: float,
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
        elif remaining_seconds < required_seconds:
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
            or active.critical_path_p95_for_workers(self._max_workers)
            > max(0.0, float(remaining_seconds))
        ):
            node = optional.pop(0)
            active = active.pruned((node.node_id,))
            removed.append(node.node_id)
        return active, tuple(removed)

    def run_parallel(
        self,
        tasks: Iterable[tuple[str, Callable[[], T]]],
        *,
        timeout_seconds: float | None = None,
        generation_scope: str = "",
    ) -> tuple[WaveOutcome, ...]:
        work = tuple(tasks)
        if not work:
            return ()
        if len({task_id for task_id, _ in work}) != len(work):
            raise ValueError("parallel wave task identities must be unique")

        generations = {
            task_id: self.issue_generation(task_id, scope=generation_scope)
            for task_id, _ in work
        }

        def invoke(task_id: str, operation: Callable[[], T]) -> WaveOutcome:
            started = perf_counter()
            try:
                value = operation()
            except Exception as error:
                return WaveOutcome(
                    task_id,
                    None,
                    error,
                    perf_counter() - started,
                    generations[task_id],
                )
            return WaveOutcome(
                task_id,
                value,
                None,
                perf_counter() - started,
                generations[task_id],
            )

        workers = min(self._max_workers, len(work))
        pool = ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="mathforge-runtime-wave",
        )
        futures: list[Future[WaveOutcome]] = [
            pool.submit(invoke, task_id, operation)
            for task_id, operation in work
        ]
        completed, pending = wait(
            futures,
            timeout=(
                None
                if timeout_seconds is None
                else max(0.0, float(timeout_seconds))
            ),
            return_when=ALL_COMPLETED,
        )
        outcomes: dict[Future[WaveOutcome], WaveOutcome] = {}
        for future in completed:
            outcome = future.result()
            outcomes[future] = replace(
                outcome,
                accepted=self.accepts_generation(
                    outcome.task_id,
                    outcome.generation,
                    scope=generation_scope,
                ),
            )
        for future in pending:
            future.cancel()
        pool.shutdown(wait=False, cancel_futures=True)
        return tuple(
            outcomes.get(
                future,
                WaveOutcome(
                    task_id,
                    None,
                    TimeoutError("parallel wave deadline reached"),
                    max(0.0, float(timeout_seconds or 0.0)),
                    generations[task_id],
                ),
            )
            for future, (task_id, _) in zip(futures, work)
        )

    def run_graph(
        self,
        graph: TaskGraph,
        *,
        initial_completed: Iterable[str] = (),
        prune_optional: Iterable[str] = (),
        timeout_seconds: float | None = None,
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
