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
    max_tokens: int = 0
    used_tokens: int = 0
    soft_deadline_seconds: float = 600.0
    exploration_deadline_seconds: float = 705.0
    hard_deadline_seconds: float = 870.0
    deterministic_finalize_reserve_seconds: float = 30.0
    model_call_start_margin_seconds: float = 135.0
    model_queue_budget_seconds: float = 15.0
    max_claims: int = 64
    max_tool_calls: int = 32
    max_isolated_tool_calls: int = 16
    max_tool_seconds: float = 30.0
    max_evidence_records: int = 256
    max_prompt_chars_total: int = 5000000
    token_limit_mode: str = "dynamic_context"
    model_context_window_tokens: int = 262144
    context_safety_margin_tokens: int = 8192

    def __post_init__(self) -> None:
        if self.max_calls < 1 or self.max_tokens < 0:
            raise ValueError("model call budget must be positive and token quota nonnegative")
        if self.token_limit_mode not in {"dynamic_context", "configured_cap"}:
            raise ValueError("token limit mode is invalid")
        if (
            self.model_context_window_tokens <= 0
            or self.context_safety_margin_tokens < 0
            or self.context_safety_margin_tokens
            >= self.model_context_window_tokens
        ):
            raise ValueError("model context window settings are invalid")
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
        if self.model_queue_budget_seconds <= 0:
            raise ValueError("model queue budget must be positive")
        self._lock = Lock()
        self._frozen = False
        self._stage_calls: dict[str, int] = {}
        self._allocation_plan: CallAllocationPlan | None = None
        self.used_claims = 0
        self.used_tool_calls = 0
        self.used_isolated_tool_calls = 0
        self.used_tool_seconds = 0.0
        self.used_evidence_records = 0
        self.used_prompt_chars = 0
        self.prompt_tokens = 0
        self.official_prompt_tokens = 0
        self.fallback_prompt_tokens = 0
        self.requested_output_tokens = 0
        self.observed_output_tokens = 0
        self.output_chars = 0
        self.model_call_elapsed_seconds = 0.0
        self.model_queue_wait_seconds = 0.0
        self.model_execution_seconds = 0.0
        self.model_call_timeout_count = 0
        self.model_queue_timeout_count = 0
        self.model_admission_rejection_count = 0
        self.model_admission_rejection_reasons: dict[str, int] = {}
        self.transport_attempts = 0
        self.model_call_failure_count = 0
        self.model_response_rejection_count = 0
        self.background_tail_started = 0
        self.background_tail_active = 0
        self.background_tail_completed = 0
        self.provider_health_state = "healthy"
        self.provider_active_tails = 0
        self.provider_peak_tails = 0
        self.provider_circuit_trips = 0
        self.provider_fast_failures = 0
        self.model_call_records: list[dict] = []
        self.final_response_tokens = 0
        self.final_response_counting_mode = ""
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
            self._ensure_mutable_locked()
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
            self._ensure_mutable_locked()
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
            self._ensure_mutable_locked()
            proposed = self.used_tokens + max(0, int(tokens))
            if self.max_tokens > 0 and proposed > self.max_tokens:
                raise BudgetExceeded("model token budget exhausted")
            self.used_tokens = proposed

    def record_model_call_started(self, stage: str, allocation: dict) -> int:
        with self._lock:
            self._ensure_mutable_locked()
            prompt_tokens = max(0, int(allocation["prompt_tokens"]))
            requested = max(0, int(allocation["max_output_tokens"]))
            mode = str(allocation["counting_mode"])
            self.prompt_tokens += prompt_tokens
            self.requested_output_tokens += requested
            if mode == "official_tokenizer":
                self.official_prompt_tokens += prompt_tokens
            else:
                self.fallback_prompt_tokens += prompt_tokens
            record = {
                "stage": str(stage),
                **dict(allocation),
                "started_elapsed_seconds": round(
                    self.deadline.elapsed_seconds(),
                    6,
                ),
                "deadline_phase": self.deadline.phase(),
                "status": "started",
                "configured_output_tokens": max(
                    0,
                    int(allocation.get("configured_output_tokens", requested)),
                ),
                "stage_output_cap_tokens": max(
                    0,
                    int(allocation.get("stage_output_cap_tokens", requested)),
                ),
                "transport_attempts": 0,
                "failure_code": "",
                "response_validation": "not_applicable",
                "observed_output_tokens": 0,
                "output_counting_mode": "",
                "output_chars": 0,
                "elapsed_seconds": 0.0,
                "queue_elapsed_seconds": 0.0,
                "execution_elapsed_seconds": 0.0,
                "total_elapsed_seconds": 0.0,
            }
            self.model_call_records.append(record)
            return len(self.model_call_records) - 1

    def record_model_call_completed(
        self,
        index: int,
        *,
        observed_output_tokens: int,
        output_counting_mode: str,
        output_chars: int,
        elapsed_seconds: float,
        transport_attempts: int = 1,
    ) -> None:
        with self._lock:
            self._ensure_mutable_locked()
            observed = max(0, int(observed_output_tokens))
            characters = max(0, int(output_chars))
            elapsed = max(0.0, float(elapsed_seconds))
            attempts = max(1, int(transport_attempts))
            self.observed_output_tokens += observed
            self.output_chars += characters
            self.model_call_elapsed_seconds += elapsed
            self.transport_attempts += attempts
            self.model_call_records[index].update(
                {
                    "status": "completed",
                    "transport_attempts": attempts,
                    "observed_output_tokens": observed,
                    "output_counting_mode": str(output_counting_mode),
                    "output_chars": characters,
                    "elapsed_seconds": round(elapsed, 6),
                }
            )

    def record_model_call_timeout(
        self,
        index: int,
        elapsed_seconds: float,
        *,
        failure_code: str = "model_response_deadline_exceeded",
        transport_attempts: int = 1,
    ) -> None:
        with self._lock:
            self._ensure_mutable_locked()
            elapsed = max(0.0, float(elapsed_seconds))
            attempts = max(1, int(transport_attempts))
            self.model_call_timeout_count += 1
            self.model_call_failure_count += 1
            self.transport_attempts += attempts
            self.model_call_elapsed_seconds += elapsed
            self.model_call_records[index].update(
                {
                    "status": "timeout",
                    "failure_code": str(failure_code),
                    "transport_attempts": attempts,
                    "elapsed_seconds": round(elapsed, 6),
                }
            )

    def record_model_call_failed(
        self,
        index: int,
        elapsed_seconds: float,
        *,
        failure_code: str = "unknown_provider_failure",
        transport_attempts: int = 1,
    ) -> None:
        with self._lock:
            self._ensure_mutable_locked()
            elapsed = max(0.0, float(elapsed_seconds))
            attempts = max(1, int(transport_attempts))
            self.model_call_failure_count += 1
            self.transport_attempts += attempts
            self.model_call_elapsed_seconds += elapsed
            self.model_call_records[index].update(
                {
                    "status": "failed",
                    "failure_code": str(failure_code),
                    "transport_attempts": attempts,
                    "elapsed_seconds": round(elapsed, 6),
                }
            )

    def record_model_response_validation(
        self,
        index: int | None,
        code: str,
        *,
        rejected: bool,
    ) -> None:
        if index is None:
            return
        with self._lock:
            self._ensure_mutable_locked()
            self.model_call_records[index]["response_validation"] = str(code)
            if rejected:
                self.model_response_rejection_count += 1

    def record_background_tail(self, event: str) -> None:
        with self._lock:
            self._ensure_mutable_locked()
            if event == "started":
                self.background_tail_started += 1
                self.background_tail_active += 1
            elif event == "completed":
                self.background_tail_completed += 1
                self.background_tail_active = max(
                    0,
                    self.background_tail_active - 1,
                )
            else:
                raise ValueError("unknown background-tail event")

    def background_tail_snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "started": self.background_tail_started,
                "active": self.background_tail_active,
                "completed": self.background_tail_completed,
            }

    def record_final_response(self, tokens: int, counting_mode: str) -> None:
        with self._lock:
            self._ensure_mutable_locked()
            self.final_response_tokens = max(0, int(tokens))
            self.final_response_counting_mode = str(counting_mode)

    def record_model_call_timing(
        self,
        index: int,
        *,
        queue_elapsed_seconds: float,
        execution_elapsed_seconds: float,
        total_elapsed_seconds: float,
    ) -> None:
        with self._lock:
            self._ensure_mutable_locked()
            queue_elapsed = max(0.0, float(queue_elapsed_seconds))
            execution_elapsed = max(0.0, float(execution_elapsed_seconds))
            total_elapsed = max(0.0, float(total_elapsed_seconds))
            self.model_queue_wait_seconds += queue_elapsed
            self.model_execution_seconds += execution_elapsed
            self.model_call_records[index].update(
                {
                    "queue_elapsed_seconds": round(queue_elapsed, 6),
                    "execution_elapsed_seconds": round(execution_elapsed, 6),
                    "total_elapsed_seconds": round(total_elapsed, 6),
                }
            )

    def record_model_admission_rejection(self, reason: str) -> None:
        with self._lock:
            self._ensure_mutable_locked()
            normalized = str(reason)
            self.model_admission_rejection_count += 1
            self.model_admission_rejection_reasons[normalized] = (
                self.model_admission_rejection_reasons.get(normalized, 0) + 1
            )
            if normalized == "model_concurrency_wait_exceeded":
                self.model_queue_timeout_count += 1

    def record_provider_health(self, snapshot: dict) -> None:
        with self._lock:
            self._ensure_mutable_locked()
            self.provider_health_state = str(snapshot.get("state", "healthy"))
            self.provider_active_tails = max(
                0,
                int(snapshot.get("active_tails", 0)),
            )
            self.provider_peak_tails = max(
                self.provider_peak_tails,
                int(snapshot.get("peak_tails", 0)),
            )
            self.provider_circuit_trips = max(
                self.provider_circuit_trips,
                int(snapshot.get("circuit_trips", 0)),
            )
            self.provider_fast_failures = max(
                self.provider_fast_failures,
                int(snapshot.get("fast_failures", 0)),
            )

    def freeze(self) -> None:
        with self._lock:
            self._frozen = True

    @property
    def is_frozen(self) -> bool:
        with self._lock:
            return self._frozen

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
            self._ensure_mutable_locked()
            proposed = self.used_claims + max(0, int(count))
            if proposed > self.max_claims:
                raise BudgetExceeded("session claim budget exhausted")
            self.used_claims = proposed

    def begin_tool_call(self, *, isolated: bool, default_timeout: float) -> float:
        with self._lock:
            self._ensure_mutable_locked()
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
            self._ensure_mutable_locked()
            self.used_tool_seconds += max(0.0, float(duration_seconds))

    def record_evidence(self, count: int = 1) -> None:
        with self._lock:
            self._ensure_mutable_locked()
            proposed = self.used_evidence_records + max(0, int(count))
            if proposed > self.max_evidence_records:
                raise BudgetExceeded("evidence record budget exhausted")
            self.used_evidence_records = proposed

    def record_prompt_chars(self, count: int) -> None:
        with self._lock:
            self._ensure_mutable_locked()
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
                "model_calls": self.used_calls,
                "max_tokens": self.max_tokens,
                "used_tokens": self.used_tokens,
                "estimated_tokens": self.used_tokens,
                "token_limit_mode": self.token_limit_mode,
                "model_context_window_tokens": self.model_context_window_tokens,
                "context_safety_margin_tokens": self.context_safety_margin_tokens,
                "prompt_tokens": self.prompt_tokens,
                "official_prompt_tokens": self.official_prompt_tokens,
                "fallback_prompt_tokens": self.fallback_prompt_tokens,
                "requested_output_tokens": self.requested_output_tokens,
                "observed_output_tokens": self.observed_output_tokens,
                "output_chars": self.output_chars,
                "model_call_elapsed_seconds": round(
                    self.model_call_elapsed_seconds,
                    6,
                ),
                "model_queue_budget_seconds": self.model_queue_budget_seconds,
                "model_queue_wait_seconds": round(
                    self.model_queue_wait_seconds,
                    6,
                ),
                "model_execution_seconds": round(
                    self.model_execution_seconds,
                    6,
                ),
                "model_call_timeout_count": self.model_call_timeout_count,
                "model_queue_timeout_count": self.model_queue_timeout_count,
                "model_admission_rejection_count": (
                    self.model_admission_rejection_count
                ),
                "model_admission_rejection_reasons": dict(
                    sorted(self.model_admission_rejection_reasons.items())
                ),
                "transport_attempts": self.transport_attempts,
                "model_call_failure_count": self.model_call_failure_count,
                "model_response_rejection_count": (
                    self.model_response_rejection_count
                ),
                "background_tail_started": self.background_tail_started,
                "background_tail_active": self.background_tail_active,
                "background_tail_completed": self.background_tail_completed,
                "provider_health_state": self.provider_health_state,
                "provider_active_tails": self.provider_active_tails,
                "provider_peak_tails": self.provider_peak_tails,
                "provider_circuit_trips": self.provider_circuit_trips,
                "provider_fast_failures": self.provider_fast_failures,
                "final_response_tokens": self.final_response_tokens,
                "final_response_counting_mode": (
                    self.final_response_counting_mode
                ),
                "model_call_records": [
                    dict(record) for record in self.model_call_records
                ],
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
                "prompt_chars": self.used_prompt_chars,
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
                "deadline_phase": self.deadline.phase(),
                "frozen": self._frozen,
            }

    def _ensure_mutable_locked(self) -> None:
        if self._frozen:
            raise RuntimeError("call budget is frozen")
