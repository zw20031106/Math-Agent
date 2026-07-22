from __future__ import annotations

from dataclasses import dataclass
from threading import Lock


@dataclass
class CallBudget:
    max_calls: int
    used_calls: int = 0

    def __post_init__(self) -> None:
        self._lock = Lock()

    def consume(self) -> None:
        with self._lock:
            if self.used_calls >= self.max_calls:
                raise RuntimeError("model call budget exhausted")
            self.used_calls += 1

    def to_dict(self) -> dict:
        with self._lock:
            return {"max_calls": self.max_calls, "used_calls": self.used_calls}
