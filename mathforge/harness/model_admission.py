from __future__ import annotations

from dataclasses import dataclass
from threading import Condition
from time import perf_counter
from typing import Callable

from mathforge.harness.priority_scheduler import PriorityCallScheduler
from mathforge.harness.rate_limit import RateReservation, WeightedRollingRateLimiter


class AdmissionWaitExceeded(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = str(code)
        super().__init__(self.code)


@dataclass(frozen=True)
class AdmissionLease:
    rate_reservation: RateReservation
    agent_key: str
    agent_wait_seconds: float
    scheduler_wait_seconds: float
    rate_wait_seconds: float


class ModelAdmissionController:
    """Atomically govern agent in-flight, concurrency, and weighted RPM."""

    def __init__(
        self,
        max_concurrency: int,
        *,
        requests_per_minute: int,
        rate_limit_window_seconds: float,
        transport_attempt_reservation: int,
        clock: Callable[[], float] = perf_counter,
        rate_limiter: WeightedRollingRateLimiter | None = None,
    ) -> None:
        if transport_attempt_reservation < 1:
            raise ValueError("transport attempt reservation must be positive")
        self._clock = clock
        self._scheduler = PriorityCallScheduler(max_concurrency, clock=clock)
        self._rate_limiter = rate_limiter or WeightedRollingRateLimiter(
            requests_per_minute,
            rate_limit_window_seconds,
            clock=clock,
        )
        self._transport_attempt_reservation = int(transport_attempt_reservation)
        self._agent_condition = Condition()
        self._active_agent_keys: set[str] = set()

    def acquire(
        self,
        stage: str,
        *,
        case_id: str,
        agent_id: str,
        timeout: float | None,
    ) -> AdmissionLease:
        started = self._clock()
        agent_key = self._agent_key(case_id, agent_id)
        self._acquire_agent_key(agent_key, timeout, started)
        agent_admitted = self._clock()
        try:
            scheduler_timeout = self._remaining_timeout(timeout, started)
            if not self._scheduler.acquire(
                stage,
                scheduler_timeout,
                case_id=case_id,
            ):
                raise AdmissionWaitExceeded("model_concurrency_wait_exceeded")
            scheduler_admitted = self._clock()
            try:
                rate_timeout = self._remaining_timeout(timeout, started)
                reservation = self._rate_limiter.reserve(
                    self._transport_attempt_reservation,
                    timeout=rate_timeout,
                )
                if reservation is None:
                    raise AdmissionWaitExceeded("model_rate_limit_wait_exceeded")
                rate_admitted = self._clock()
            except Exception:
                self._scheduler.release()
                raise
        except Exception:
            self._release_agent_key(agent_key)
            raise
        return AdmissionLease(
            reservation,
            agent_key,
            max(0.0, agent_admitted - started),
            max(0.0, scheduler_admitted - agent_admitted),
            max(0.0, rate_admitted - scheduler_admitted),
        )

    def commit(self, lease: AdmissionLease) -> None:
        self._rate_limiter.commit(lease.rate_reservation)

    def release(self, lease: AdmissionLease, *, dispatched: bool) -> None:
        if not dispatched:
            self._rate_limiter.refund(lease.rate_reservation)
        self._scheduler.release()
        self._release_agent_key(lease.agent_key)

    def snapshot(self) -> dict[str, object]:
        with self._agent_condition:
            active_agent_calls = len(self._active_agent_keys)
        return {
            "scheduler": self._scheduler.snapshot(),
            "rate_limit": self._rate_limiter.snapshot(),
            "active_agent_calls": active_agent_calls,
            "transport_attempt_reservation": self._transport_attempt_reservation,
        }

    def _acquire_agent_key(
        self,
        agent_key: str,
        timeout: float | None,
        started: float,
    ) -> None:
        if not agent_key:
            return
        with self._agent_condition:
            while agent_key in self._active_agent_keys:
                if timeout is None:
                    self._agent_condition.wait()
                    continue
                remaining = timeout - (self._clock() - started)
                if remaining <= 0:
                    raise AdmissionWaitExceeded(
                        "model_agent_inflight_wait_exceeded"
                    )
                self._agent_condition.wait(remaining)
            self._active_agent_keys.add(agent_key)

    def _release_agent_key(self, agent_key: str) -> None:
        if not agent_key:
            return
        with self._agent_condition:
            self._active_agent_keys.discard(agent_key)
            self._agent_condition.notify_all()

    def _remaining_timeout(
        self,
        timeout: float | None,
        started: float,
    ) -> float | None:
        if timeout is None:
            return None
        return max(0.0, timeout - (self._clock() - started))

    @staticmethod
    def _agent_key(case_id: str, agent_id: str) -> str:
        normalized_case = str(case_id).strip()
        normalized_agent = str(agent_id).strip()
        if not normalized_case or not normalized_agent:
            return ""
        return f"{normalized_case}:{normalized_agent}"
