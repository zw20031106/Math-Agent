from __future__ import annotations

from dataclasses import dataclass
from threading import Condition
from time import perf_counter
from typing import Callable


_STAGE_PRIORITY = {
    "primary": 0,
    "router": 0,
    "alternative": 1,
    "repair": 2,
    "lemma": 2,
    "verifier": 3,
    "finalizer": 3,
    "unallocated": 4,
}
_ANSWER_FORMATION_STAGES = frozenset({"router", "primary", "alternative"})


@dataclass(frozen=True)
class _Waiter:
    sequence: int
    stage: str
    priority: int
    case_id: str
    queued_at: float


class PriorityCallScheduler:
    """Bound calls with answer-first stage aging and case round-robin."""

    def __init__(
        self,
        capacity: int,
        *,
        aging_interval_seconds: float = 10.0,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        if capacity < 1:
            raise ValueError("scheduler capacity must be positive")
        if aging_interval_seconds <= 0:
            raise ValueError("aging interval must be positive")
        self._capacity = int(capacity)
        self._available = int(capacity)
        self._active = 0
        self._peak = 0
        self._sequence = 0
        self._admission_sequence = 0
        self._waiters: list[_Waiter] = []
        self._case_last_admitted: dict[str, int] = {}
        self._aging_interval_seconds = float(aging_interval_seconds)
        self._clock = clock
        self._condition = Condition()

    def acquire(
        self,
        stage: str,
        timeout: float | None = None,
        *,
        case_id: str = "",
    ) -> bool:
        if timeout is not None and timeout < 0:
            return False
        started = self._clock()
        with self._condition:
            self._sequence += 1
            normalized_stage = str(stage)
            normalized_case = str(case_id).strip() or f"anonymous:{self._sequence}"
            waiter = _Waiter(
                sequence=self._sequence,
                stage=normalized_stage,
                priority=_STAGE_PRIORITY.get(
                    normalized_stage,
                    _STAGE_PRIORITY["unallocated"],
                ),
                case_id=normalized_case,
                queued_at=started,
            )
            self._waiters.append(waiter)
            while True:
                head = self._next_waiter(self._clock())
                if self._available > 0 and head == waiter:
                    self._waiters.remove(waiter)
                    self._available -= 1
                    self._active += 1
                    self._peak = max(self._peak, self._active)
                    self._admission_sequence += 1
                    self._case_last_admitted[waiter.case_id] = (
                        self._admission_sequence
                    )
                    self._condition.notify_all()
                    return True
                if timeout is None:
                    self._condition.wait()
                    continue
                remaining = timeout - (self._clock() - started)
                if remaining <= 0:
                    self._waiters.remove(waiter)
                    self._condition.notify_all()
                    return False
                self._condition.wait(remaining)

    def _next_waiter(self, now: float) -> _Waiter:
        ranked = [
            (self._effective_priority(waiter, now), waiter)
            for waiter in self._waiters
        ]
        best_priority = min(priority for priority, _ in ranked)
        eligible = [
            waiter for priority, waiter in ranked if priority == best_priority
        ]
        return min(
            eligible,
            key=lambda item: (
                self._case_last_admitted.get(item.case_id, 0),
                item.sequence,
            ),
        )

    def _effective_priority(self, waiter: _Waiter, now: float) -> int:
        age_steps = min(
            2,
            int(
                max(0.0, now - waiter.queued_at)
                // self._aging_interval_seconds
            ),
        )
        priority = max(0, waiter.priority - age_steps)
        if (
            waiter.stage not in _ANSWER_FORMATION_STAGES
            and any(
                item.stage in _ANSWER_FORMATION_STAGES
                for item in self._waiters
            )
            and age_steps == 0
        ):
            return max(1, priority)
        return priority

    def release(self) -> None:
        with self._condition:
            if self._active < 1:
                raise RuntimeError("model call scheduler released without an active call")
            self._active -= 1
            self._available += 1
            self._condition.notify_all()

    def snapshot(self) -> dict[str, object]:
        with self._condition:
            now = self._clock()
            queued_by_stage: dict[str, int] = {}
            for waiter in self._waiters:
                queued_by_stage[waiter.stage] = (
                    queued_by_stage.get(waiter.stage, 0) + 1
                )
            return {
                "capacity": self._capacity,
                "active": self._active,
                "peak": self._peak,
                "queued": len(self._waiters),
                "queued_by_stage": dict(sorted(queued_by_stage.items())),
                "oldest_queue_seconds": round(
                    max(
                        (
                            max(0.0, now - waiter.queued_at)
                            for waiter in self._waiters
                        ),
                        default=0.0,
                    ),
                    6,
                ),
                "admissions": self._admission_sequence,
            }
