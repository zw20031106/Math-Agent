from __future__ import annotations

from concurrent.futures import ALL_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass
from hashlib import sha256
from time import perf_counter
from typing import Callable, Iterable, TypeVar

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
        return payload


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


class SchedulerFlow:
    """Deterministic DAG, closure admission, and bounded parallel-wave service."""

    def __init__(self, *, max_workers: int) -> None:
        if max_workers < 1:
            raise ValueError("scheduler worker capacity must be positive")
        self._max_workers = int(max_workers)

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

    def run_parallel(
        self,
        tasks: Iterable[tuple[str, Callable[[], T]]],
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[WaveOutcome, ...]:
        work = tuple(tasks)
        if not work:
            return ()
        if len({task_id for task_id, _ in work}) != len(work):
            raise ValueError("parallel wave task identities must be unique")

        def invoke(task_id: str, operation: Callable[[], T]) -> WaveOutcome:
            started = perf_counter()
            try:
                value = operation()
            except Exception as error:
                return WaveOutcome(task_id, None, error, perf_counter() - started)
            return WaveOutcome(task_id, value, None, perf_counter() - started)

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
        outcomes: dict[Future[WaveOutcome], WaveOutcome] = {
            future: future.result() for future in completed
        }
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
                ),
            )
            for future, (task_id, _) in zip(futures, work)
        )
