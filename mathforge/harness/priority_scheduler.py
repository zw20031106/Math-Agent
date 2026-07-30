from __future__ import annotations

from dataclasses import dataclass
from threading import Condition
from time import perf_counter


_STAGE_PRIORITY = {
    "primary": 0,
    "verifier": 1,
    "repair": 2,
    "alternative": 3,
    "lemma": 4,
    "router": 5,
    "finalizer": 6,
    "unallocated": 7,
}


@dataclass(frozen=True)
class _Waiter:
    sequence: int
    priority: int


class PriorityCallScheduler:
    """Bound physical calls and admit queued work by stage priority, then FIFO."""

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("scheduler capacity must be positive")
        self._capacity = int(capacity)
        self._available = int(capacity)
        self._active = 0
        self._peak = 0
        self._sequence = 0
        self._waiters: list[_Waiter] = []
        self._condition = Condition()

    def acquire(self, stage: str, timeout: float | None = None) -> bool:
        if timeout is not None and timeout < 0:
            return False
        started = perf_counter()
        with self._condition:
            self._sequence += 1
            waiter = _Waiter(
                sequence=self._sequence,
                priority=_STAGE_PRIORITY.get(stage, _STAGE_PRIORITY["unallocated"]),
            )
            self._waiters.append(waiter)
            while True:
                head = min(
                    self._waiters,
                    key=lambda item: (item.priority, item.sequence),
                )
                if self._available > 0 and head == waiter:
                    self._waiters.remove(waiter)
                    self._available -= 1
                    self._active += 1
                    self._peak = max(self._peak, self._active)
                    self._condition.notify_all()
                    return True
                if timeout is None:
                    self._condition.wait()
                    continue
                remaining = timeout - (perf_counter() - started)
                if remaining <= 0:
                    self._waiters.remove(waiter)
                    self._condition.notify_all()
                    return False
                self._condition.wait(remaining)

    def release(self) -> None:
        with self._condition:
            if self._active < 1:
                raise RuntimeError("model call scheduler released without an active call")
            self._active -= 1
            self._available += 1
            self._condition.notify_all()

    def snapshot(self) -> dict[str, int]:
        with self._condition:
            return {
                "capacity": self._capacity,
                "active": self._active,
                "peak": self._peak,
                "queued": len(self._waiters),
            }
