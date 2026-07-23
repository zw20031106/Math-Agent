from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from mathforge.harness.allocation import CallAllocationPlan
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
    model_call_start_margin_seconds: float = 0.0
    max_claims: int = 64
    max_tool_calls: int = 32
    max_isolated_tool_calls: int = 16
    max_tool_seconds: float = 30.0
    max_evidence_records: int = 256
    max_prompt_chars_total: int = 200000

    def __post_init__(self) -> None:
        if self.max_calls < 1 or self.max_tokens < 1:
            raise ValueError("model call and token budgets must be positive")
        if not 1 <= self.max_claims <= 64:
            raise ValueError("max_claims must be in [1, 64]")
        if self.max_tool_calls < 1 or self.max_isolated_tool_calls < 1:
            raise ValueError("tool call budgets must be positive")
        if self.max_isolated_tool_calls > self.max_tool_calls:
            raise ValueError(
                "max_isolated_tool_calls must not exceed max_tool_calls"
            )
        if self.max_tool_seconds <= 0:
            raise ValueError("max_tool_seconds must be positive")
        if self.max_evidence_records < 1 or self.max_prompt_chars_total < 1:
            raise ValueError("evidence and prompt budgets must be positive")
        self._lock = Lock()
        self._stage_calls: dict[str, int] = {}
        self._allocation_plan: CallAllocationPlan | None = None
        self.used_claims = 0
        self.used_tool_calls = 0
        self.used_isolated_tool_calls = 0
        self.used_tool_seconds = 0.0
        self.used_evidence_records = 0
        self.used_prompt_chars = 0
        self.deadline = DeadlineController(
            soft_deadline_seconds=self.soft_deadline_seconds,
            exploration_deadline_seconds=self.exploration_deadline_seconds,
            hard_deadline_seconds=self.hard_deadline_seconds,
            deterministic_finalize_reserve_seconds=(
                self.deterministic_finalize_reserve_seconds
            ),
            model_call_start_margin_seconds=self.model_call_start_margin_seconds,
        )

    def set_allocation_plan(self, plan: CallAllocationPlan) -> None:
        with self._lock:
            if plan.max_calls != self.max_calls:
                raise ValueError("call allocation plan does not match budget")
            for stage, used in self._stage_calls.items():
                if used > plan.limit_for(stage):
                    raise ValueError(
                        f"existing {stage} calls exceed allocation plan"
                    )
            self._allocation_plan = plan

    def consume(self, *, stage: str = "unallocated", optional: bool = False) -> None:
        with self._lock:
            if self.used_calls >= self.max_calls:
                raise BudgetExceeded("model call budget exhausted")
            if self._allocation_plan is not None:
                used_for_stage = self._stage_calls.get(stage, 0)
                if used_for_stage >= self._allocation_plan.limit_for(stage):
                    raise BudgetExceeded(f"{stage} call allocation exhausted")
            if not self.deadline.can_start_model_call(optional=optional):
                raise BudgetExceeded("model call deadline reached")
            self.used_calls += 1
            self._stage_calls[stage] = self._stage_calls.get(stage, 0) + 1

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

    def ensure_stage(self, stage: str, *, optional: bool = False) -> None:
        if not self.deadline.can_start_stage(optional=optional):
            raise BudgetExceeded(f"{stage} deadline reached")

    def record_claims(self, count: int) -> None:
        with self._lock:
            proposed = self.used_claims + max(0, int(count))
            if proposed > self.max_claims:
                raise BudgetExceeded("session claim budget exhausted")
            self.used_claims = proposed

    def begin_tool_call(self, *, isolated: bool, default_timeout: float) -> float:
        with self._lock:
            if self.used_tool_calls >= self.max_tool_calls:
                raise BudgetExceeded("tool call budget exhausted")
            if isolated and self.used_isolated_tool_calls >= self.max_isolated_tool_calls:
                raise BudgetExceeded("isolated tool call budget exhausted")
            remaining_tool_seconds = self.max_tool_seconds - self.used_tool_seconds
            remaining_deadline = self.deadline.remaining_for_stage()
            timeout = min(
                max(0.0, float(default_timeout)),
                remaining_tool_seconds,
                remaining_deadline,
            )
            if timeout <= 0:
                raise BudgetExceeded("tool time budget exhausted")
            self.used_tool_calls += 1
            if isolated:
                self.used_isolated_tool_calls += 1
            return timeout

    def finish_tool_call(self, duration_seconds: float) -> None:
        with self._lock:
            self.used_tool_seconds += max(0.0, float(duration_seconds))

    def record_evidence(self, count: int = 1) -> None:
        with self._lock:
            proposed = self.used_evidence_records + max(0, int(count))
            if proposed > self.max_evidence_records:
                raise BudgetExceeded("evidence record budget exhausted")
            self.used_evidence_records = proposed

    def record_prompt_chars(self, count: int) -> None:
        with self._lock:
            proposed = self.used_prompt_chars + max(0, int(count))
            if proposed > self.max_prompt_chars_total:
                raise BudgetExceeded("prompt character budget exhausted")
            self.used_prompt_chars = proposed

    def _elapsed(self) -> float:
        return self.deadline.elapsed_seconds()

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "max_calls": self.max_calls,
                "used_calls": self.used_calls,
                "max_tokens": self.max_tokens,
                "used_tokens": self.used_tokens,
                "max_claims": self.max_claims,
                "used_claims": self.used_claims,
                "max_tool_calls": self.max_tool_calls,
                "used_tool_calls": self.used_tool_calls,
                "max_isolated_tool_calls": self.max_isolated_tool_calls,
                "used_isolated_tool_calls": self.used_isolated_tool_calls,
                "max_tool_seconds": self.max_tool_seconds,
                "used_tool_seconds": round(self.used_tool_seconds, 6),
                "max_evidence_records": self.max_evidence_records,
                "used_evidence_records": self.used_evidence_records,
                "max_prompt_chars_total": self.max_prompt_chars_total,
                "used_prompt_chars": self.used_prompt_chars,
                "call_allocation": (
                    self._allocation_plan.to_dict()
                    if self._allocation_plan is not None
                    else None
                ),
                "elapsed_seconds": round(self._elapsed(), 6),
                "remaining_seconds": round(self.deadline.remaining_seconds(), 6),
                "finalize_reserve_seconds": self.deadline.finalize_reserve_seconds,
                "soft_expired": self.soft_expired(),
                "exploration_open": self.can_start_exploration(),
            }
