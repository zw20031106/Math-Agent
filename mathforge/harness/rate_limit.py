from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Condition
from time import monotonic
from typing import Callable


@dataclass(frozen=True)
class RateReservation:
    token: int
    weight: int
    admitted_at: float


class WeightedRollingRateLimiter:
    """Reserve weighted physical requests in a rolling time window."""

    def __init__(
        self,
        limit: int,
        window_seconds: float,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if type(limit) is not int or limit < 1:
            raise ValueError("rate limit must be a positive integer")
        if window_seconds <= 0:
            raise ValueError("rate limit window must be positive")
        self._limit = limit
        self._window_seconds = float(window_seconds)
        self._clock = clock
        self._condition = Condition()
        self._events: deque[RateReservation] = deque()
        self._committed: set[int] = set()
        self._next_token = 0
        self._admitted_weight = 0
        self._peak_weight = 0
        self._wait_count = 0

    def reserve(
        self,
        weight: int,
        timeout: float | None = None,
    ) -> RateReservation | None:
        if type(weight) is not int or not 1 <= weight <= self._limit:
            raise ValueError("reservation weight must be within the rate limit")
        if timeout is not None and timeout < 0:
            return None
        started = self._clock()
        with self._condition:
            while True:
                now = self._clock()
                self._expire_locked(now)
                used = sum(item.weight for item in self._events)
                if used + weight <= self._limit:
                    self._next_token += 1
                    reservation = RateReservation(
                        token=self._next_token,
                        weight=weight,
                        admitted_at=now,
                    )
                    self._events.append(reservation)
                    self._admitted_weight += weight
                    self._peak_weight = max(self._peak_weight, used + weight)
                    return reservation
                if timeout == 0:
                    return None
                self._wait_count += 1
                until_release = max(
                    0.0,
                    self._events[0].admitted_at + self._window_seconds - now,
                )
                if timeout is None:
                    self._condition.wait(until_release)
                    continue
                remaining = timeout - (now - started)
                if remaining <= 0:
                    return None
                self._condition.wait(min(remaining, until_release))

    def try_reserve(self, weight: int) -> RateReservation | None:
        return self.reserve(weight, timeout=0.0)

    def commit(self, reservation: RateReservation) -> None:
        with self._condition:
            if not any(item.token == reservation.token for item in self._events):
                raise RuntimeError("rate reservation is no longer active")
            self._committed.add(reservation.token)

    def refund(self, reservation: RateReservation) -> bool:
        """Refund only a reservation that never reached client.chat."""

        with self._condition:
            if reservation.token in self._committed:
                return False
            for index, item in enumerate(self._events):
                if item.token == reservation.token:
                    del self._events[index]
                    self._condition.notify_all()
                    return True
            return False

    def snapshot(self) -> dict[str, int | float]:
        with self._condition:
            self._expire_locked(self._clock())
            return {
                "limit": self._limit,
                "window_seconds": self._window_seconds,
                "reserved_weight": sum(item.weight for item in self._events),
                "reservation_count": len(self._events),
                "committed_count": len(self._committed),
                "admitted_weight": self._admitted_weight,
                "peak_weight": self._peak_weight,
                "wait_count": self._wait_count,
            }

    def _expire_locked(self, now: float) -> None:
        changed = False
        while (
            self._events
            and now - self._events[0].admitted_at >= self._window_seconds
        ):
            expired = self._events.popleft()
            self._committed.discard(expired.token)
            changed = True
        if changed:
            self._condition.notify_all()
