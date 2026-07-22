from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CallBudget:
    max_calls: int
    used_calls: int = 0

    def consume(self) -> None:
        if self.used_calls >= self.max_calls:
            raise RuntimeError("model call budget exhausted")
        self.used_calls += 1

    def to_dict(self) -> dict:
        return {"max_calls": self.max_calls, "used_calls": self.used_calls}
