from __future__ import annotations

from threading import Event, Lock

from mathforge.harness.errors import ModelCallRejected


class CancellationToken:
    """Thread-safe, one-way cancellation shared by one problem session."""

    def __init__(self) -> None:
        self._event = Event()
        self._lock = Lock()
        self._reason = ""

    def cancel(self, reason: str = "case_cancelled") -> bool:
        normalized = str(reason).strip() or "case_cancelled"
        with self._lock:
            if self._event.is_set():
                return False
            self._reason = normalized
            self._event.set()
            return True

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise ModelCallRejected("case_cancelled")

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)

    def snapshot(self) -> dict[str, str | bool]:
        return {
            "cancelled": self.is_cancelled,
            "reason": self.reason,
        }
