from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from mathforge.harness.deadline import DeadlineController
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
    deterministic_finalize_reserve_seconds: float = 5.0

    def __post_init__(self) -> None:
        self._lock = Lock()
        self.deadline = DeadlineController(
            soft_deadline_seconds=self.soft_deadline_seconds,
            exploration_deadline_seconds=self.exploration_deadline_seconds,
            hard_deadline_seconds=self.hard_deadline_seconds,
            deterministic_finalize_reserve_seconds=(
                self.deterministic_finalize_reserve_seconds
            ),
        )

    def consume(self, *, optional: bool = False) -> None:
        with self._lock:
            if self.used_calls >= self.max_calls:
                raise BudgetExceeded("model call budget exhausted")
            if not self.deadline.can_start_model_call(optional=optional):
                raise BudgetExceeded("model call deadline reached")
            self.used_calls += 1

    def record_tokens(self, tokens: int) -> None:
        with self._lock:
            proposed = self.used_tokens + max(0, int(tokens))
            if proposed > self.max_tokens:
                raise BudgetExceeded("model token budget exhausted")
            self.used_tokens = proposed

    def soft_expired(self) -> bool:
        return not self.deadline.optional_work_allowed()

    def can_start_exploration(self) -> bool:
        return self.deadline.exploration_allowed()

    def must_finalize(self) -> bool:
        return self.deadline.must_finalize()

    def _elapsed(self) -> float:
        return self.deadline.elapsed_seconds()

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "max_calls": self.max_calls,
                "used_calls": self.used_calls,
                "max_tokens": self.max_tokens,
                "used_tokens": self.used_tokens,
                "elapsed_seconds": round(self._elapsed(), 6),
                "remaining_seconds": round(self.deadline.remaining_seconds(), 6),
                "finalize_reserve_seconds": self.deadline.finalize_reserve_seconds,
                "soft_expired": self.soft_expired(),
                "exploration_open": self.can_start_exploration(),
            }
