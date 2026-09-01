from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import ceil
from threading import Lock
from typing import ClassVar

from mathforge.agent_runtime.call_ledger import CallLedger
from mathforge.agent_runtime.resource_governor import ResourceGovernor
from mathforge.harness.budget_types import CallBudgetSnapshot
from mathforge.harness.cancellation import CancellationToken
from mathforge.harness.deadline import DeadlineController
from mathforge.harness.errors import BudgetExceeded
from mathforge.harness.model_policy import stage_call_timeout


ANSWER_SOURCE_LEVELS = ("L1", "L2", "L3", "L4", "L5")


class AnswerSourceCounts(dict):
    """Five-level counts with a backwards-compatible two-level equality."""

    def __eq__(self, other) -> bool:  # pragma: no cover - compatibility branch
        if isinstance(other, dict) and set(other) == {"L1", "L5"}:
            return all(self.get(key, 0) == int(value) for key, value in other.items()) and all(
                self.get(key, 0) == 0 for key in ANSWER_SOURCE_LEVELS[1:4]
            )
        return dict.__eq__(self, other)


@dataclass
class CallBudget:
    PROMPT_COMPONENT_KEYS: ClassVar[tuple[str, ...]] = (
        "contract_tokens",
        "runtime_protocol_tokens",
        "skill_tokens",
        "state_tokens",
        "problem_tokens",
        "schema_tokens",
    )

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
    model_call_policy: str = "adaptive_bounded"
    stage_execution_policy: dict[str, dict[str, int | float]] | None = None
    soft_call_checkpoints: tuple[int, ...] = ()
    speculative_exploration_cutoff: int = 0
    closure_reserve_calls: int = 0
    enforce_stage_start_window: bool = False
    require_scheduler_binding: bool = False
    cancellation_token: CancellationToken | None = None

    def __post_init__(self) -> None:
        if self.max_calls < 1 or self.max_tokens < 0:
            raise ValueError("model call budget must be positive and token quota nonnegative")
        if type(self.require_scheduler_binding) is not bool:
            raise ValueError("require_scheduler_binding must be a boolean")
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
        self.soft_call_checkpoints = tuple(self.soft_call_checkpoints)
        if self.speculative_exploration_cutoff == 0:
            self.speculative_exploration_cutoff = (
                self.max_calls - self.closure_reserve_calls
            )
        if self.model_call_policy != "adaptive_bounded":
            raise ValueError("model call policy is invalid")
        self._lock = Lock()
        if self.cancellation_token is None:
            self.cancellation_token = CancellationToken()
        self._frozen = False
        self._scheduler_case_id = ""
        self._agent_runtime = None
        self._stage_calls: dict[str, int] = {}
        self.used_claims = 0
        self.used_tool_calls = 0
        self.used_isolated_tool_calls = 0
        self.used_tool_seconds = 0.0
        self.used_evidence_records = 0
        self.used_prompt_chars = 0
        self.prompt_tokens = 0
        self.prompt_component_tokens = {
            name: 0 for name in self.PROMPT_COMPONENT_KEYS
        }
        self.official_prompt_tokens = 0
        self.fallback_prompt_tokens = 0
        self.tokenizer_fallback_count = 0
        self.requested_output_tokens = 0
        self.observed_output_tokens = 0
        self._observed_output_window: deque[int] = deque(maxlen=8)
        self._reserved_output_tokens = 0
        self._pending_output_predictions: deque[int] = deque()
        self._active_output_predictions: deque[int] = deque()
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
        self.retry_count = 0
        self.retry_reasons: dict[str, int] = {}
        self.background_tail_started = 0
        self.background_tail_active = 0
        self.background_tail_completed = 0
        self.provider_health_state = "healthy"
        self.provider_active_tails = 0
        self.provider_peak_tails = 0
        self.provider_scheduler_peak = 0
        self.provider_rate_reserved_weight = 0
        self.provider_rate_peak_weight = 0
        self.provider_rate_wait_count = 0
        self.provider_rate_admitted_weight = 0
        self.provider_circuit_trips = 0
        self.provider_fast_failures = 0
        self.protocol_health_state = "healthy"
        self.protocol_success_count = 0
        self.protocol_recovery_count = 0
        self.protocol_failure_count = 0
        self.cognitive_health_state = "healthy"
        self.cognitive_rejection_count = 0
        self._call_ledger = CallLedger()
        self.model_call_records = self._call_ledger.records
        self._resource_governor = ResourceGovernor(
            hard_limit=self.max_calls,
            soft_checkpoints=self.soft_call_checkpoints,
            speculative_exploration_cutoff=(
                self.speculative_exploration_cutoff
            ),
            closure_reserve_calls=self.closure_reserve_calls,
            cancellation_token=self.cancellation_token,
        )
        self.final_response_tokens = 0
        self.final_response_counting_mode = ""
        # Phase 0 observability: retain the terminal answer path even when a
        # candidate is rejected later in the workflow.  The initial profile
        # intentionally exposes only the two stable states; the full ladder
        # is introduced by the answer-delivery phase.
        self.answer_source = "L5"
        self.answer_source_counts = AnswerSourceCounts(
            {level: 0 for level in ANSWER_SOURCE_LEVELS}
        )
        self.deadline = DeadlineController(
            soft_deadline_seconds=self.soft_deadline_seconds,
            exploration_deadline_seconds=self.exploration_deadline_seconds,
            hard_deadline_seconds=self.hard_deadline_seconds,
            deterministic_finalize_reserve_seconds=(
                self.deterministic_finalize_reserve_seconds
            ),
            model_call_start_margin_seconds=self.model_call_start_margin_seconds,
        )

    def bind_scheduler_case(self, case_id: str) -> None:
        normalized = str(case_id).strip()
        if not normalized:
            raise ValueError("scheduler case id must be non-empty")
        with self._lock:
            self._ensure_mutable_locked()
            if self._scheduler_case_id and self._scheduler_case_id != normalized:
                raise RuntimeError("scheduler case id is already bound")
            self._scheduler_case_id = normalized

    @property
    def scheduler_case_id(self) -> str:
        with self._lock:
            return self._scheduler_case_id

    def bind_agent_runtime(self, runtime) -> None:
        with self._lock:
            self._ensure_mutable_locked()
            if runtime.session_id != self._scheduler_case_id:
                raise ValueError("Agent runtime must match the scheduler session")
            self._agent_runtime = runtime
            runtime.bind_cancellation_token(self.cancellation_token)

    @property
    def agent_runtime(self):
        with self._lock:
            return self._agent_runtime

    def release_agent_runtime(self) -> None:
        with self._lock:
            self._agent_runtime = None

    def consume(
        self,
        *,
        stage: str = "unallocated",
        optional: bool = False,
        action_category: str | None = None,
        stage_timeout_seconds: float | None = None,
    ) -> None:
        with self._lock:
            self._ensure_mutable_locked()
            self._ensure_active_locked()
            category = action_category or ResourceGovernor.default_action_category(
                stage,
                optional=optional,
            )
            self._resource_governor.admit(
                used_calls=self.used_calls,
                action_category=category,
            )
            can_start = (
                self.deadline.can_start_model_call(optional=optional)
                if stage_timeout_seconds is None
                else self.deadline.can_start_stage_call(
                    stage_timeout=stage_timeout_seconds,
                    optional=optional,
                )
            )
            if not can_start:
                rejection_reason = (
                    "model_stage_window_insufficient"
                    if stage_timeout_seconds is not None
                    else "model_response_deadline_exceeded"
                )
                self.model_admission_rejection_count += 1
                self.model_admission_rejection_reasons[rejection_reason] = (
                    self.model_admission_rejection_reasons.get(
                        rejection_reason,
                        0,
                    )
                    + 1
                )
                if self.deadline.hard_expired():
                    self.cancellation_token.cancel("case_deadline_expired")
                raise BudgetExceeded("model call deadline reached")
            predicted_output = self._predicted_output_tokens_locked()
            if (
                self.max_tokens > 0
                and predicted_output > 0
                and self.used_tokens
                + self._reserved_output_tokens
                + predicted_output
                > self.max_tokens
            ):
                raise BudgetExceeded("model token budget admission exhausted")
            self._pending_output_predictions.append(predicted_output)
            self._reserved_output_tokens += predicted_output
            self.used_calls += 1
            self._stage_calls[stage] = self._stage_calls.get(stage, 0) + 1

    def refund(self, *, stage: str = "unallocated") -> bool:
        """Return a reservation only when no provider request was dispatched."""
        with self._lock:
            self._ensure_mutable_locked()
            used_for_stage = self._stage_calls.get(stage, 0)
            if self.used_calls <= 0 or used_for_stage <= 0:
                return False
            self.used_calls -= 1
            if used_for_stage == 1:
                self._stage_calls.pop(stage, None)
            else:
                self._stage_calls[stage] = used_for_stage - 1
            self._release_output_prediction_locked()
            return True

    def record_tokens(self, tokens: int) -> None:
        with self._lock:
            self._ensure_mutable_locked()
            proposed = self.used_tokens + max(0, int(tokens))
            if self.max_tokens > 0 and proposed > self.max_tokens:
                raise BudgetExceeded("model token budget exhausted")
            self.used_tokens = proposed

    def record_tokenizer_fallback(self, count: int = 1) -> None:
        """Record an in-process tokenizer fallback for run diagnostics."""

        with self._lock:
            self._ensure_mutable_locked()
            self.tokenizer_fallback_count += max(0, int(count))

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
                "logical_call_index": self.used_calls,
                "logical_call_consumed": False,
                "dispatched": False,
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
                "transport_attempt_reservation": max(
                    1,
                    int(allocation.get("transport_attempt_reservation", 1)),
                ),
                "transport_attempt_observability": str(
                    allocation.get(
                        "transport_attempt_observability",
                        "pending",
                    )
                ),
                "failure_code": "",
                "response_validation": "not_applicable",
                "protocol_parse_tier": "not_attempted",
                "protocol_recovery_reason": "",
                "protocol_assurance_degradation": "none",
                "candidate_parse_tier": "not_attempted",
                "observed_output_tokens": 0,
                "predicted_output_tokens": self._take_output_prediction_locked(),
                "output_counting_mode": "",
                "output_chars": 0,
                "output_budget_exceeded": False,
                "truncation_status": "unknown",
                "finish_reason": str(
                    allocation.get("finish_reason", "unobservable")
                ),
                "tail_state": "none",
                "stop_reason": "",
                "elapsed_seconds": 0.0,
                "queue_elapsed_seconds": 0.0,
                "agent_wait_seconds": 0.0,
                "scheduler_wait_seconds": 0.0,
                "rate_wait_seconds": 0.0,
                "execution_elapsed_seconds": 0.0,
                "total_elapsed_seconds": 0.0,
            }
            return self._call_ledger.start(record)

    def record_model_call_dispatched(self, index: int) -> None:
        with self._lock:
            self._ensure_mutable_locked()
            self._call_ledger.update(
                index,
                {"dispatched": True, "logical_call_consumed": True},
            )

    def record_model_call_lineage(self, index: int, lineage: dict) -> None:
        with self._lock:
            self._ensure_mutable_locked()
            self._call_ledger.update(index, dict(lineage))

    def record_model_call_finished(
        self,
        index: int,
        *,
        observed_output_tokens: int,
        output_counting_mode: str,
        output_chars: int,
        elapsed_seconds: float,
        transport_attempts: int = 1,
        output_budget_exceeded: bool = False,
        finish_reason: str = "",
        truncation_status: str = "complete",
    ) -> None:
        with self._lock:
            self._ensure_mutable_locked()
            observed = max(0, int(observed_output_tokens))
            characters = max(0, int(output_chars))
            elapsed = max(0.0, float(elapsed_seconds))
            attempts = max(1, int(transport_attempts))
            status = str(truncation_status).strip().casefold()
            if status not in {"complete", "suspect", "truncated"}:
                raise ValueError("invalid truncation status")
            truncated = bool(output_budget_exceeded or status == "truncated")
            self._release_output_prediction_locked()
            self._observed_output_window.append(observed)
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
                    "output_budget_exceeded": bool(
                        output_budget_exceeded
                    ),
                    "finish_reason": str(finish_reason),
                    "truncation_status": status,
                    "response_truncated": truncated,
                    "elapsed_seconds": round(elapsed, 6),
                    "stop_reason": "response_received",
                }
            )

    def record_model_call_completed(
        self,
        index: int,
        *,
        observed_output_tokens: int,
        output_counting_mode: str,
        output_chars: int,
        elapsed_seconds: float,
        transport_attempts: int = 1,
        output_budget_exceeded: bool = False,
        finish_reason: str = "",
        truncation_status: str = "complete",
    ) -> None:
        """Backward-compatible alias for the observed-use accounting API."""

        self.record_model_call_finished(
            index,
            observed_output_tokens=observed_output_tokens,
            output_counting_mode=output_counting_mode,
            output_chars=output_chars,
            elapsed_seconds=elapsed_seconds,
            transport_attempts=transport_attempts,
            output_budget_exceeded=output_budget_exceeded,
            finish_reason=finish_reason,
            truncation_status=truncation_status,
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
            self._release_output_prediction_locked()
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
                    "stop_reason": str(failure_code),
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
            self._release_output_prediction_locked()
            self.model_call_failure_count += 1
            self.transport_attempts += attempts
            self.model_call_elapsed_seconds += elapsed
            self.model_call_records[index].update(
                {
                    "status": "failed",
                    "failure_code": str(failure_code),
                    "transport_attempts": attempts,
                    "elapsed_seconds": round(elapsed, 6),
                    "stop_reason": str(failure_code),
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
                self.cognitive_rejection_count += 1
                self.cognitive_health_state = "degraded"

    def record_model_protocol_telemetry(
        self,
        index: int | None,
        parse_tier: str,
        recovery_reason: str = "",
        assurance_degradation: str = "none",
        *,
        candidate_parse_tier: str = "",
    ) -> None:
        if index is None:
            return
        with self._lock:
            self._ensure_mutable_locked()
            update = {
                "protocol_parse_tier": str(parse_tier),
                "protocol_recovery_reason": str(recovery_reason),
                "protocol_assurance_degradation": str(
                    assurance_degradation
                ),
            }
            if candidate_parse_tier:
                update["candidate_parse_tier"] = str(candidate_parse_tier)
            self._call_ledger.update(index, update)
            normalized = str(parse_tier).casefold()
            degradation = str(assurance_degradation).casefold()
            if normalized in {"strict", "host_wrapped"} and degradation in {
                "",
                "none",
            }:
                self.protocol_success_count += 1
            elif normalized in {"rejected", "failed", "not_attempted"}:
                self.protocol_failure_count += 1
                self.protocol_health_state = "degraded"
            else:
                self.protocol_recovery_count += 1
                self.protocol_health_state = "degraded"

    def record_background_tail(self, event: str, index: int | None = None) -> None:
        with self._lock:
            self._ensure_mutable_locked()
            if event == "started":
                self.background_tail_started += 1
                self.background_tail_active += 1
                if index is not None:
                    self.model_call_records[index]["tail_state"] = "background_tail"
            elif event == "completed":
                self.background_tail_completed += 1
                self.background_tail_active = max(
                    0,
                    self.background_tail_active - 1,
                )
                if index is not None:
                    self.model_call_records[index]["tail_state"] = "completed_late"
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

    def record_answer_source(self, source: str) -> None:
        """Record the final answer path for this case exactly once.

        Phase 0 deliberately distinguishes only a retained candidate (L1)
        from the no-candidate fallback (L5).  Re-recording replaces the prior
        value so a defensive caller cannot inflate the per-case count.
        """

        normalized = str(source).strip().upper()
        if normalized not in ANSWER_SOURCE_LEVELS:
            raise ValueError(
                "answer source must be one of " + ", ".join(ANSWER_SOURCE_LEVELS)
            )
        with self._lock:
            self._ensure_mutable_locked()
            self.answer_source = normalized
            self.answer_source_counts = AnswerSourceCounts(
                {level: int(level == normalized) for level in ANSWER_SOURCE_LEVELS}
            )

    def record_model_call_timing(
        self,
        index: int,
        *,
        queue_elapsed_seconds: float,
        agent_wait_seconds: float = 0.0,
        scheduler_wait_seconds: float = 0.0,
        rate_wait_seconds: float = 0.0,
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
                    "agent_wait_seconds": round(
                        max(0.0, float(agent_wait_seconds)),
                        6,
                    ),
                    "scheduler_wait_seconds": round(
                        max(0.0, float(scheduler_wait_seconds)),
                        6,
                    ),
                    "rate_wait_seconds": round(
                        max(0.0, float(rate_wait_seconds)),
                        6,
                    ),
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
            transport = snapshot.get("transport_health", snapshot)
            if not isinstance(transport, dict):
                transport = snapshot
            self.provider_health_state = str(transport.get("state", "healthy"))
            self.provider_active_tails = max(
                0,
                int(transport.get("active_tails", 0)),
            )
            self.provider_peak_tails = max(
                self.provider_peak_tails,
                int(transport.get("peak_tails", 0)),
            )
            self.provider_circuit_trips = max(
                self.provider_circuit_trips,
                int(transport.get("circuit_trips", 0)),
            )
            self.provider_fast_failures = max(
                self.provider_fast_failures,
                int(transport.get("fast_failures", 0)),
            )
            scheduler = snapshot.get("scheduler", {})
            if isinstance(scheduler, dict):
                self.provider_scheduler_peak = max(
                    self.provider_scheduler_peak,
                    int(scheduler.get("peak", 0)),
                )
            rate_limit = snapshot.get("rate_limit", {})
            if isinstance(rate_limit, dict):
                self.provider_rate_reserved_weight = max(
                    0,
                    int(rate_limit.get("reserved_weight", 0)),
                )
                self.provider_rate_peak_weight = max(
                    self.provider_rate_peak_weight,
                    int(rate_limit.get("peak_weight", 0)),
                )
                self.provider_rate_wait_count = max(
                    self.provider_rate_wait_count,
                    int(rate_limit.get("wait_count", 0)),
                )
                self.provider_rate_admitted_weight = max(
                    self.provider_rate_admitted_weight,
                    int(rate_limit.get("admitted_weight", 0)),
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
        return self.deadline.exploration_allowed() and (
            self.used_calls
            < self._resource_governor.speculative_exploration_cutoff
        )

    def must_finalize(self) -> bool:
        return self.deadline.must_finalize()

    def ensure_stage(self, stage: str, *, optional: bool = False) -> None:
        if self.cancellation_token.is_cancelled:
            raise BudgetExceeded(f"{stage} cancelled")
        if not self.deadline.can_start_stage(optional=optional):
            if self.deadline.hard_expired():
                self.cancellation_token.cancel("case_deadline_expired")
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
            self._ensure_active_locked()
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

    def record_prompt_chars(
        self,
        count: int,
        *,
        components: dict[str, int] | None = None,
    ) -> None:
        with self._lock:
            self._ensure_mutable_locked()
            proposed = self.used_prompt_chars + max(0, int(count))
            if proposed > self.max_prompt_chars_total:
                raise BudgetExceeded("prompt character budget exhausted")
            self.used_prompt_chars = proposed
            if components:
                unknown = set(components) - set(self.PROMPT_COMPONENT_KEYS)
                if unknown:
                    raise ValueError(
                        "unknown prompt component token fields: "
                        + ", ".join(sorted(unknown))
                    )
                for name in self.PROMPT_COMPONENT_KEYS:
                    value = components.get(name, 0)
                    if type(value) is not int or value < 0:
                        raise ValueError(
                            f"prompt component {name} must be a nonnegative integer"
                        )
                    self.prompt_component_tokens[name] += value

    def record_prompt_components(self, components: dict[str, int]) -> None:
        """Record token components without charging prompt characters twice."""

        self.record_prompt_chars(0, components=components)

    def record_model_retry(self, reason: str) -> None:
        normalized = str(reason).strip() or "unspecified"
        with self._lock:
            self._ensure_mutable_locked()
            self.retry_count += 1
            self.retry_reasons[normalized] = (
                self.retry_reasons.get(normalized, 0) + 1
            )

    def observed_output_tokens_mean(self) -> float:
        """Return the bounded observed-output mean used for admission."""

        with self._lock:
            return self._observed_output_tokens_mean_locked()

    def stage_timeout_seconds(self, stage: str) -> float:
        """Resolve a stage timeout from the active competition policy."""

        return stage_call_timeout(stage, self.stage_execution_policy)

    def _observed_output_tokens_mean_locked(self) -> float:
        if not self._observed_output_window:
            return 0.0
        return sum(self._observed_output_window) / len(
            self._observed_output_window
        )

    def _predicted_output_tokens_locked(self) -> int:
        mean = self._observed_output_tokens_mean_locked()
        return max(0, int(ceil(mean)))

    def _take_output_prediction_locked(self) -> int:
        prediction = (
            self._pending_output_predictions.popleft()
            if self._pending_output_predictions
            else 0
        )
        self._active_output_predictions.append(prediction)
        return prediction

    def _release_output_prediction_locked(self) -> None:
        if self._active_output_predictions:
            prediction = self._active_output_predictions.popleft()
        elif self._pending_output_predictions:
            prediction = self._pending_output_predictions.popleft()
        else:
            prediction = 0
        self._reserved_output_tokens = max(
            0,
            self._reserved_output_tokens - prediction,
        )

    def _elapsed(self) -> float:
        return self.deadline.elapsed_seconds()

    def snapshot(self) -> CallBudgetSnapshot:
        with self._lock:
            remaining_calls = max(0, self.max_calls - self.used_calls)
            stage_remaining = {
                stage: remaining_calls
                for stage in (
                    "router",
                    "primary",
                    "alternative",
                    "verifier",
                    "repair",
                    "lemma",
                    "finalizer",
                )
            }
            return CallBudgetSnapshot(
                max_calls=self.max_calls,
                used_calls=self.used_calls,
                remaining_calls=remaining_calls,
                remaining_seconds=round(
                    self.deadline.remaining_seconds(),
                    6,
                ),
                exploration_open=self.can_start_exploration(),
                stage_remaining=stage_remaining,
                budget_phase=self.budget_phase,
                next_checkpoint=self._resource_governor.next_checkpoint(
                    self.used_calls
                ),
            )

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "max_calls": self.max_calls,
                "used_calls": self.used_calls,
                "calls_used": self.used_calls,
                "model_calls": self.used_calls,
                "model_call_policy": self.model_call_policy,
                "budget_phase": self.budget_phase,
                "soft_call_checkpoints": list(self.soft_call_checkpoints),
                "speculative_exploration_cutoff": (
                    self.speculative_exploration_cutoff
                ),
                "closure_reserve_calls": self.closure_reserve_calls,
                "enforce_stage_start_window": self.enforce_stage_start_window,
                "require_scheduler_binding": self.require_scheduler_binding,
                "calls_remaining": max(0, self.max_calls - self.used_calls),
                "max_tokens": self.max_tokens,
                "used_tokens": self.used_tokens,
                "estimated_tokens": self.used_tokens,
                "token_limit_mode": self.token_limit_mode,
                "model_context_window_tokens": self.model_context_window_tokens,
                "context_safety_margin_tokens": self.context_safety_margin_tokens,
                "prompt_tokens": self.prompt_tokens,
                "prompt_component_tokens": dict(self.prompt_component_tokens),
                "official_prompt_tokens": self.official_prompt_tokens,
                "fallback_prompt_tokens": self.fallback_prompt_tokens,
                "tokenizer_fallback_count": self.tokenizer_fallback_count,
                "requested_output_tokens": self.requested_output_tokens,
                "observed_output_tokens": self.observed_output_tokens,
                "observed_output_tokens_mean": round(
                    self._observed_output_tokens_mean_locked(),
                    6,
                ),
                "observed_output_tokens_window": list(
                    self._observed_output_window
                ),
                "reserved_output_tokens": self._reserved_output_tokens,
                "output_chars": self.output_chars,
                "model_call_elapsed_seconds": round(
                    self.model_call_elapsed_seconds,
                    6,
                ),
                "model_queue_budget_seconds": self.model_queue_budget_seconds,
                "scheduler_case_bound": bool(self._scheduler_case_id),
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
                "retry_count": self.retry_count,
                "retry_reasons": dict(sorted(self.retry_reasons.items())),
                "background_tail_started": self.background_tail_started,
                "background_tail_active": self.background_tail_active,
                "background_tail_completed": self.background_tail_completed,
                "provider_health_state": self.provider_health_state,
                "provider_active_tails": self.provider_active_tails,
                "provider_peak_tails": self.provider_peak_tails,
                "provider_scheduler_peak": self.provider_scheduler_peak,
                "provider_rate_reserved_weight": (
                    self.provider_rate_reserved_weight
                ),
                "provider_rate_peak_weight": self.provider_rate_peak_weight,
                "provider_rate_wait_count": self.provider_rate_wait_count,
                "provider_rate_admitted_weight": (
                    self.provider_rate_admitted_weight
                ),
                "provider_circuit_trips": self.provider_circuit_trips,
                "provider_fast_failures": self.provider_fast_failures,
                "transport_health": {
                    "state": self.provider_health_state,
                    "active_tails": self.provider_active_tails,
                    "peak_tails": self.provider_peak_tails,
                    "circuit_trips": self.provider_circuit_trips,
                    "fast_failures": self.provider_fast_failures,
                },
                "protocol_health": {
                    "state": self.protocol_health_state,
                    "success_count": self.protocol_success_count,
                    "recovery_count": self.protocol_recovery_count,
                    "failure_count": self.protocol_failure_count,
                },
                "cognitive_health": {
                    "state": self.cognitive_health_state,
                    "rejection_count": self.cognitive_rejection_count,
                },
                "cancellation": self.cancellation_token.snapshot(),
                "final_response_tokens": self.final_response_tokens,
                "final_response_counting_mode": (
                    self.final_response_counting_mode
                ),
                "answer_source": self.answer_source,
                "answer_source_counts": AnswerSourceCounts(self.answer_source_counts),
                "model_call_records": self._call_ledger.snapshot(),
                "call_accounting": self._call_ledger.accounting_snapshot(),
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
                "stage_quotas_enforced": False,
                "elapsed_seconds": round(self._elapsed(), 6),
                "remaining_seconds": round(self.deadline.remaining_seconds(), 6),
                "finalize_reserve_seconds": self.deadline.finalize_reserve_seconds,
                "soft_expired": self.soft_expired(),
                "exploration_open": self.can_start_exploration(),
                "deadline_phase": self.deadline.phase(),
                "frozen": self._frozen,
            }

    @property
    def budget_phase(self) -> str:
        return self._resource_governor.phase(self.used_calls)

    @property
    def resource_governor(self) -> ResourceGovernor:
        return self._resource_governor

    def _ensure_mutable_locked(self) -> None:
        if self._frozen:
            raise RuntimeError("call budget is frozen")

    def _ensure_active_locked(self) -> None:
        if self.cancellation_token.is_cancelled:
            raise BudgetExceeded("case cancellation requested")


class SessionCallBudget(CallBudget):
    """Named F1 budget used by the production per-problem Session."""
