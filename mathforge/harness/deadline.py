from __future__ import annotations

from math import isfinite
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
        return max(
            0.0,
            self.remaining_seconds()
            - self.finalize_reserve_seconds
            - self.model_call_start_margin_seconds,
        )

    def remaining_for_stage(self) -> float:
        return self.remaining_seconds()

    def optional_work_allowed(self) -> bool:
        return self.elapsed_seconds() < self.soft_deadline_seconds

    def exploration_allowed(self) -> bool:
        return (
            self.elapsed_seconds() < self.exploration_deadline_seconds
            and self.remaining_for_model_call() > 0
        )

    def can_start_model_call(self, *, optional: bool = False) -> bool:
        if optional and not self.optional_work_allowed():
            return False
        return self.exploration_allowed()

    def can_start_stage_call(
        self,
        *,
        stage_timeout: float,
        optional: bool = False,
    ) -> bool:
        """Check whether one concrete stage can still finish safely.

        The old admission check only looked at the global model-call margin.
        That made a long stage start with too little time left and left the
        request running after the case had already reached its hard deadline.
        Admission is now tied to the stage's actual timeout and the
        deterministic-finalization reserve.  A short, bounded stage remains
        eligible after the exploration deadline so a late answer-extraction
        or finalization step can still publish a result.
        """

        try:
            timeout = float(stage_timeout)
        except (TypeError, ValueError) as error:
            raise ValueError("stage timeout must be a nonnegative number") from error
        if not isfinite(timeout) or timeout < 0:
            raise ValueError("stage timeout must be a nonnegative number")
        if optional and not self.optional_work_allowed():
            return False
        if timeout <= 0:
            return False

        remaining = self.remaining_seconds()
        reserve = self.finalize_reserve_seconds
        # A configured stage timeout can exceed a synthetic/test deadline.
        # The provider will clip the actual wait to the available window, so
        # use that same hard upper bound for feasibility instead of making an
        # otherwise valid short-deadline call impossible to exercise.
        bounded_timeout = min(timeout, max(0.0, self.hard_deadline_seconds - reserve))
        required_window = bounded_timeout + reserve
        # Keep a strict reserve for normal configured stages: an exact fit
        # leaves no scheduling/cleanup margin.  Synthetic callers may pass a
        # timeout larger than their hard deadline; the provider clips that
        # timeout to the test window, so retain the historical exact-fit
        # compatibility for that case.
        fits_window = (
            remaining > required_window
            if timeout <= self.hard_deadline_seconds
            else remaining >= required_window
        )
        if not fits_window:
            return False
        if timeout <= 60.0:
            return True
        return self.elapsed_seconds() < self.exploration_deadline_seconds

    def can_start_stage(self, *, optional: bool = False) -> bool:
        if optional and not self.optional_work_allowed():
            return False
        return self.remaining_for_stage() > 0

    def must_finalize(self) -> bool:
        return self.remaining_seconds() <= self.finalize_reserve_seconds

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

