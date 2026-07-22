from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from time import monotonic

from mathforge.harness.errors import BudgetExceeded


@dataclass
class CallBudget:
    max_calls: int
    used_calls: int = 0
    max_tokens: int = 24000
    used_tokens: int = 0
    soft_deadline_seconds: float = 720.0
    exploration_deadline_seconds: float = 780.0
    hard_deadline_seconds: float = 870.0
    _started_at: float = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._lock = Lock()
        self._started_at = monotonic()
        if not 0 < self.soft_deadline_seconds <= self.exploration_deadline_seconds <= self.hard_deadline_seconds:
            raise ValueError("deadline thresholds must be positive and ordered")

    def consume(self) -> None:
        with self._lock:
            if self.used_calls >= self.max_calls:
                raise BudgetExceeded("model call budget exhausted")
            if self._elapsed() >= self.hard_deadline_seconds:
                raise BudgetExceeded("hard deadline reached")
            self.used_calls += 1

    def record_tokens(self, tokens: int) -> None:
        with self._lock:
            proposed = self.used_tokens + max(0, int(tokens))
            if proposed > self.max_tokens:
                raise BudgetExceeded("model token budget exhausted")
            self.used_tokens = proposed

    def soft_expired(self) -> bool:
        return self._elapsed() >= self.soft_deadline_seconds

    def can_start_exploration(self) -> bool:
        return self._elapsed() < self.exploration_deadline_seconds

    def must_finalize(self) -> bool:
        return self._elapsed() >= self.hard_deadline_seconds

    def _elapsed(self) -> float:
        return monotonic() - self._started_at

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "max_calls": self.max_calls,
                "used_calls": self.used_calls,
                "max_tokens": self.max_tokens,
                "used_tokens": self.used_tokens,
                "elapsed_seconds": round(self._elapsed(), 6),
                "soft_expired": self._elapsed() >= self.soft_deadline_seconds,
                "exploration_open": self._elapsed() < self.exploration_deadline_seconds,
            }
