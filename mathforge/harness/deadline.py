from __future__ import annotations

from time import monotonic
from typing import Callable


class DeadlineController:
    """Single monotonic clock shared by every stage of one solve."""

    def __init__(
        self,
        *,
        soft_deadline_seconds: float,
        exploration_deadline_seconds: float,
        hard_deadline_seconds: float,
        deterministic_finalize_reserve_seconds: float,
        model_call_start_margin_seconds: float = 0.0,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if not (
            0
            < soft_deadline_seconds
            <= exploration_deadline_seconds
            <= hard_deadline_seconds
        ):
            raise ValueError("deadline thresholds must be positive and ordered")
        if not 0 <= deterministic_finalize_reserve_seconds < hard_deadline_seconds:
            raise ValueError(
                "deterministic finalize reserve must be nonnegative and below hard deadline"
            )
        if model_call_start_margin_seconds < 0:
            raise ValueError("model call start margin must be nonnegative")
        self.soft_deadline_seconds = soft_deadline_seconds
        self.exploration_deadline_seconds = exploration_deadline_seconds
        self.hard_deadline_seconds = hard_deadline_seconds
        self.finalize_reserve_seconds = deterministic_finalize_reserve_seconds
        self.model_call_start_margin_seconds = model_call_start_margin_seconds
        self._clock = clock
        self._started_at = clock()

    def elapsed_seconds(self) -> float:
        return max(0.0, self._clock() - self._started_at)

    def remaining_seconds(self) -> float:
        return max(0.0, self.hard_deadline_seconds - self.elapsed_seconds())

    def remaining_for_model_call(self) -> float:
        return max(0.0, self.remaining_seconds() - self.finalize_reserve_seconds)

    def remaining_for_stage(self) -> float:
        return max(0.0, self.remaining_seconds() - self.finalize_reserve_seconds)

    def optional_work_allowed(self) -> bool:
        return self.elapsed_seconds() < self.soft_deadline_seconds

    def exploration_allowed(self) -> bool:
        return (
            self.elapsed_seconds() < self.exploration_deadline_seconds
            and self.remaining_for_model_call()
            > self.model_call_start_margin_seconds
        )

    def can_start_model_call(self, *, optional: bool = False) -> bool:
        if optional and not self.optional_work_allowed():
            return False
        return self.exploration_allowed()

    def can_start_stage(self, *, optional: bool = False) -> bool:
        if optional and not self.optional_work_allowed():
            return False
        return self.remaining_for_stage() > 0

    def must_finalize(self) -> bool:
        return self.remaining_for_model_call() <= 0

    def hard_expired(self) -> bool:
        return self.remaining_seconds() <= 0

    def phase(self) -> str:
        if self.hard_expired():
            return "hard_expired"
        if self.must_finalize():
            return "deterministic_finalize"
        if not self.exploration_allowed():
            return "local_validation_only"
        if not self.optional_work_allowed():
            return "evidence_driven_exploration"
        return "normal"

