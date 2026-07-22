from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mathforge.harness.budget import CallBudget


@dataclass
class MathSession:
    session_id: str
    problem: str
    metadata: dict[str, Any]
    budget: CallBudget
    trace_events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "problem": self.problem,
            "metadata": dict(self.metadata),
            "budget": self.budget.to_dict(),
            "trace_events": [dict(event) for event in self.trace_events],
        }
