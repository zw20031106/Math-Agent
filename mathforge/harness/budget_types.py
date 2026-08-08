from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CallBudgetSnapshot:
    max_calls: int
    used_calls: int
    remaining_calls: int
    remaining_seconds: float
    exploration_open: bool
    stage_remaining: dict[str, int]
    budget_phase: str = "exploration"
    next_checkpoint: int | None = None

    def to_dict(self) -> dict:
        return {
            "max_calls": self.max_calls,
            "used_calls": self.used_calls,
            "remaining_calls": self.remaining_calls,
            "remaining_seconds": self.remaining_seconds,
            "exploration_open": self.exploration_open,
            "stage_remaining": dict(self.stage_remaining),
            "budget_phase": self.budget_phase,
            "next_checkpoint": self.next_checkpoint,
        }


@dataclass(frozen=True)
class FanoutDecision:
    requested_candidates: int
    admitted_candidates: int
    reason_codes: tuple[str, ...]
    budget: CallBudgetSnapshot

    def to_dict(self) -> dict:
        return {
            "requested_candidates": self.requested_candidates,
            "admitted_candidates": self.admitted_candidates,
            "reason_codes": list(self.reason_codes),
            "budget": self.budget.to_dict(),
        }
