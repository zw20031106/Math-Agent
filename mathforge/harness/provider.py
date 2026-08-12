from __future__ import annotations

from copy import deepcopy
from collections.abc import Callable
from collections import deque
from threading import Event, Lock, Thread
from time import perf_counter
from typing import Any, TYPE_CHECKING

from mathforge.context.errors import ContextBudgetExceeded
from mathforge.agent_runtime.resource_governor import ResourceGovernor
from mathforge.harness.context_budget import ModelContextBudget
from mathforge.harness.errors import BudgetExceeded
from mathforge.harness.errors import ModelCallRejected
from mathforge.harness.errors import ModelTransportError
from mathforge.harness.cancellation import CancellationToken
from mathforge.harness.model_policy import (
    PROVIDER_CALL_TIMEOUT_SECONDS,
    effective_call_timeout,
    effective_output_tokens,
    feasible_queue_budget,
    stage_call_timeout,
    stage_minimum_start_window,
    stage_output_cap,
    stage_p95_seconds,
)
from mathforge.harness.model_admission import (
    AdmissionWaitExceeded,
    ModelAdmissionController,
)
from mathforge.harness.transport import (
    ObservedModelResponse,
    classify_transport_failure,
    transport_attempt_observation,
)

if TYPE_CHECKING:
    from mathforge.harness.budget import CallBudget
    from mathforge.harness.deadline import DeadlineController


_TRANSPORT_HEALTH_FAILURE_CODES = frozenset(
    {
        "auth_or_permission_failure",
        "rate_limited",
        "provider_5xx",
        "network_connect_failure",
        "network_read_timeout",
        "empty_response",
        "unknown_provider_failure",
    }
)


def _record_protocol_dispatch(budget, call_index, runtime, turn) -> None:
    budget.record_model_call_dispatched(call_index)
    if runtime is not None and turn is not None:
        try:
            runtime.mark_dispatched(
                turn.turn_id,
                budget_snapshot={
                    "used_calls": budget.used_calls,
                    "max_calls": budget.max_calls,
                },
            )
        except Exception:
            budget.record_model_call_lineage(
                call_index,
                {"agent_protocol_status": "shadow_dispatch_failed"},
            )


def _fail_protocol_turn(runtime, turn, failure_code: str) -> None:
    if runtime is None or turn is None:
        return
    try:
        runtime.fail_model_turn(turn.turn_id, failure_code)
    except Exception:
        return


def _complete_protocol_turn(
    runtime,
    turn,
    response: str,
    *,
    agent_action_protocol: bool = False,
    response_truncated: bool = False,
    truncation_reason: str = "",
) -> dict:
    if runtime is None or turn is None:
        return {}
    try:
        if not agent_action_protocol and not response_truncated:
            return runtime.complete_model_turn(turn.turn_id, response)
        return runtime.complete_model_turn(
            turn.turn_id,
            response,
            agent_action_protocol=agent_action_protocol,
            response_truncated=response_truncated,
            truncation_reason=truncation_reason,
        )
    except Exception:
        return {"agent_protocol_status": "shadow_publish_failed"}


class ModelCallGate:
    """Bound concurrent access to the shared official client."""

    def __init__(
        self,
        max_concurrency: int,
        *,
        requests_per_minute: int = 200,
        rate_limit_window_seconds: float = 60.0,
        transport_attempt_reservation: int = 3,
        max_background_tails: int | None = None,
        late_registry_limit: int = 64,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        tail_limit = (
            max_concurrency
            if max_background_tails is None
            else int(max_background_tails)
        )
        if tail_limit < max_concurrency:
            raise ValueError(
                "max_background_tails must cover admitted model concurrency"
            )
        if late_registry_limit < 1:
            raise ValueError("late_registry_limit must be positive")
        self._admission = ModelAdmissionController(
            max_concurrency,
            requests_per_minute=requests_per_minute,
            rate_limit_window_seconds=rate_limit_window_seconds,
            transport_attempt_reservation=transport_attempt_reservation,
        )
        self._max_background_tails = tail_limit
        self._late_registry_limit = int(late_registry_limit)
        self._health_lock = Lock()
        self._health_state = "healthy"
        self._active_tails = 0
        self._peak_tails = 0
        self._circuit_trips = 0
        self._fast_failures = 0
        self._health_window: deque[bool] = deque(maxlen=8)
        self._ordinary_failure_count = 0
        self._ordinary_success_count = 0
        self._consecutive_failures = 0
        self._next_call_index = 0
        self._late_registry: list[dict[str, Any]] = []
        self._discarded_cancelled_results = 0
        self._protocol_success_count = 0
        self._protocol_failure_count = 0

    def call(
        self,
        function,
        /,
        *,
        deadline=None,
        background_tail_callback=None,
        stage: str = "unallocated",
        case_id: str = "",
        agent_id: str = "",
        queue_budget_seconds: float | None = None,
        stage_timeout_seconds: float | None = None,
        minimum_start_window_seconds: float = 0.0,
        timing_callback=None,
        dispatch_callback=None,
        cancellation_token: CancellationToken | None = None,
        **kwargs,
    ):
        self._raise_if_cancelled(cancellation_token)
        if deadline is None:
            self._reject_open_circuit(timing_callback)
            try:
                lease = self._admission.acquire(
                    stage,
                    case_id=case_id,
                    agent_id=agent_id,
                    timeout=None,
                )
            except AdmissionWaitExceeded as error:
                raise ModelCallRejected(error.code) from error
            dispatched = False
            released = False
            try:
                self._raise_if_cancelled(cancellation_token)
                if dispatch_callback is not None:
                    dispatch_callback()
                self._admission.commit(lease)
                dispatched = True
                outcome = function(**kwargs)
                attempts, observed = transport_attempt_observation(outcome)
                if observed:
                    self._admission.release(
                        lease,
                        dispatched=True,
                        observed_attempts=attempts,
                    )
                    released = True
                return outcome
            finally:
                if not released:
                    self._admission.release(lease, dispatched=dispatched)

        self._reject_open_circuit(timing_callback)
        started = perf_counter()
        stage_timeout = (
            stage_call_timeout(stage)
            if stage_timeout_seconds is None
            else max(0.0, float(stage_timeout_seconds))
        )
        queue_budget = (
            deadline.remaining_for_model_call()
            if queue_budget_seconds is None
            else max(0.0, float(queue_budget_seconds))
        )
        acquire_timeout = max(
            0.0,
            min(queue_budget, deadline.remaining_for_model_call()),
        )
        try:
            lease = self._admission.acquire(
                stage,
                case_id=case_id,
                agent_id=agent_id,
                timeout=acquire_timeout,
            )
        except AdmissionWaitExceeded as error:
            queue_elapsed = perf_counter() - started
            self._emit_timing(
                timing_callback,
                queue_elapsed_seconds=queue_elapsed,
                agent_wait_seconds=0.0,
                scheduler_wait_seconds=0.0,
                rate_wait_seconds=0.0,
                execution_elapsed_seconds=0.0,
                total_elapsed_seconds=queue_elapsed,
            )
            raise ModelCallRejected(error.code) from error
        queue_elapsed = perf_counter() - started
        try:
            self._raise_if_cancelled(cancellation_token)
            self._reject_open_circuit(timing_callback, queue_elapsed)
        except ModelCallRejected:
            self._admission.release(lease, dispatched=False)
            raise
        if not deadline.can_start_model_call():
            self._admission.release(lease, dispatched=False)
            self._emit_timing(
                timing_callback,
                queue_elapsed_seconds=queue_elapsed,
                agent_wait_seconds=lease.agent_wait_seconds,
                scheduler_wait_seconds=lease.scheduler_wait_seconds,
                rate_wait_seconds=lease.rate_wait_seconds,
                execution_elapsed_seconds=0.0,
                total_elapsed_seconds=queue_elapsed,
            )
            raise ModelCallRejected("model_response_deadline_exceeded")

        execution_timeout = max(
            0.0,
            min(
                stage_timeout,
                deadline.remaining_for_model_call(),
            ),
        )
        minimum_start_window = max(
            0.0,
            float(minimum_start_window_seconds),
        )
        if execution_timeout < minimum_start_window:
            self._admission.release(lease, dispatched=False)
            self._emit_timing(
                timing_callback,
                queue_elapsed_seconds=queue_elapsed,
                agent_wait_seconds=lease.agent_wait_seconds,
                scheduler_wait_seconds=lease.scheduler_wait_seconds,
                rate_wait_seconds=lease.rate_wait_seconds,
                execution_elapsed_seconds=0.0,
                total_elapsed_seconds=queue_elapsed,
            )
            raise ModelCallRejected("model_stage_window_insufficient")
        if execution_timeout <= 0:
            self._admission.release(lease, dispatched=False)
            self._emit_timing(
                timing_callback,
                queue_elapsed_seconds=queue_elapsed,
                agent_wait_seconds=lease.agent_wait_seconds,
                scheduler_wait_seconds=lease.scheduler_wait_seconds,
                rate_wait_seconds=lease.rate_wait_seconds,
                execution_elapsed_seconds=0.0,
                total_elapsed_seconds=queue_elapsed,
            )
            raise ModelCallRejected("model_response_deadline_exceeded")

        done = Event()
        outcome: dict[str, Any] = {}
        state_lock = Lock()
        state = {"completed": False, "timed_out": False}
        execution_started = perf_counter()
        call_index = self._allocate_call_index()
        try:
            self._raise_if_cancelled(cancellation_token)
        except ModelCallRejected:
            self._admission.release(lease, dispatched=False)
            raise
        if dispatch_callback is not None:
            try:
                dispatch_callback()
            except Exception:
                self._admission.release(lease, dispatched=False)
                raise
        self._admission.commit(lease)

        def invoke() -> None:
            try:
                value = function(**kwargs)
                if cancellation_token is None or not cancellation_token.is_cancelled:
                    outcome["value"] = value
            except BaseException as exc:
                if cancellation_token is None or not cancellation_token.is_cancelled:
                    outcome["error"] = exc
            finally:
                with state_lock:
                    state["completed"] = True
                    is_background_tail = state["timed_out"]
                    cancelled = (
                        cancellation_token is not None
                        and cancellation_token.is_cancelled
                    )
                observed_value = outcome.get("error", outcome.get("value"))
                attempts, observed = transport_attempt_observation(
                    observed_value
                )
                self._admission.release(
                    lease,
                    dispatched=True,
                    observed_attempts=attempts if observed else None,
                )
                done.set()
                if is_background_tail:
                    self._complete_tail(
                        call_index,
                        completion_status=(
                            "failed" if "error" in outcome else "completed"
                        ),
                        elapsed_seconds=perf_counter() - execution_started,
                    )
                    if background_tail_callback is not None:
                        try:
                            background_tail_callback("completed")
                        except Exception:
                            pass
                elif cancelled:
                    with self._health_lock:
                        self._discarded_cancelled_results += 1

        Thread(
            target=invoke,
            name="mathforge-model-call",
            daemon=True,
        ).start()
        wait_started = perf_counter()
        while True:
            remaining_wait = execution_timeout - (perf_counter() - wait_started)
            if remaining_wait <= 0 or done.wait(min(0.05, remaining_wait)):
                break
            if (
                cancellation_token is not None
                and cancellation_token.is_cancelled
            ):
                execution_elapsed = perf_counter() - execution_started
                self._emit_timing(
                    timing_callback,
                    queue_elapsed_seconds=queue_elapsed,
                    agent_wait_seconds=lease.agent_wait_seconds,
                    scheduler_wait_seconds=lease.scheduler_wait_seconds,
                    rate_wait_seconds=lease.rate_wait_seconds,
                    execution_elapsed_seconds=execution_elapsed,
                    total_elapsed_seconds=perf_counter() - started,
                )
                raise ModelCallRejected("case_cancelled", dispatched=True)
        if not done.is_set():
            with state_lock:
                already_completed = state["completed"]
                if not already_completed:
                    state["timed_out"] = True
                    self._register_tail(call_index)
            if not already_completed:
                if background_tail_callback is not None:
                    background_tail_callback("started")
                execution_elapsed = perf_counter() - execution_started
                self._emit_timing(
                    timing_callback,
                    queue_elapsed_seconds=queue_elapsed,
                    agent_wait_seconds=lease.agent_wait_seconds,
                    scheduler_wait_seconds=lease.scheduler_wait_seconds,
                    rate_wait_seconds=lease.rate_wait_seconds,
                    execution_elapsed_seconds=execution_elapsed,
                    total_elapsed_seconds=perf_counter() - started,
                )
                raise ModelCallRejected(
                    "model_response_deadline_exceeded",
                    dispatched=True,
                )
        if cancellation_token is not None and cancellation_token.is_cancelled:
            raise ModelCallRejected("case_cancelled", dispatched=True)
        execution_elapsed = perf_counter() - execution_started
        self._emit_timing(
            timing_callback,
            queue_elapsed_seconds=queue_elapsed,
            agent_wait_seconds=lease.agent_wait_seconds,
            scheduler_wait_seconds=lease.scheduler_wait_seconds,
            rate_wait_seconds=lease.rate_wait_seconds,
            execution_elapsed_seconds=execution_elapsed,
            total_elapsed_seconds=perf_counter() - started,
        )
        if "error" in outcome:
            raise outcome["error"]
        return outcome.get("value")

    def health_snapshot(self) -> dict[str, Any]:
        with self._health_lock:
            transport_health = {
                "state": self._health_state,
                "active_tails": self._active_tails,
                "peak_tails": self._peak_tails,
                "circuit_trips": self._circuit_trips,
                "fast_failures": self._fast_failures,
                "ordinary_failure_count": self._ordinary_failure_count,
                "ordinary_success_count": self._ordinary_success_count,
                "consecutive_failures": self._consecutive_failures,
                "health_window_failures": sum(
                    not outcome for outcome in self._health_window
                ),
                "health_window_size": len(self._health_window),
                "late_registry": deepcopy(self._late_registry),
            }
            return {
                **transport_health,
                "transport_health": deepcopy(transport_health),
                "protocol_health": {
                    "state": (
                        "degraded" if self._protocol_failure_count else "healthy"
                    ),
                    "success_count": self._protocol_success_count,
                    "failure_count": self._protocol_failure_count,
                },
                "discarded_cancelled_results": (
                    self._discarded_cancelled_results
                ),
                **self._admission.snapshot(),
            }

    def record_provider_result(
        self,
        *,
        success: bool,
        failure_code: str = "",
    ) -> None:
        """Record a provider result that was actually dispatched.

        Queue rejection and deadline admission are scheduler events, not
        provider health signals.  This method is called by the provider only
        after the injected client's ``chat`` call has been dispatched or after
        its response shape has been checked.
        """

        if not success and failure_code not in _TRANSPORT_HEALTH_FAILURE_CODES:
            return
        with self._health_lock:
            outcome = bool(success)
            self._health_window.append(outcome)
            if outcome:
                self._ordinary_success_count += 1
                self._consecutive_failures = 0
            else:
                self._ordinary_failure_count += 1
                self._consecutive_failures += 1
            self._recompute_health_locked()

    def record_protocol_result(self, *, success: bool) -> None:
        with self._health_lock:
            if success:
                self._protocol_success_count += 1
            else:
                self._protocol_failure_count += 1

    @property
    def transport_attempt_reservation(self) -> int:
        return self._admission.transport_attempt_reservation

    @staticmethod
    def _raise_if_cancelled(
        cancellation_token: CancellationToken | None,
    ) -> None:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()

    def _reject_open_circuit(
        self,
        timing_callback,
        queue_elapsed_seconds: float = 0.0,
    ) -> None:
        with self._health_lock:
            if self._health_state != "circuit_open":
                return
            self._fast_failures += 1
        self._emit_timing(
            timing_callback,
            queue_elapsed_seconds=queue_elapsed_seconds,
            execution_elapsed_seconds=0.0,
            total_elapsed_seconds=queue_elapsed_seconds,
        )
        raise ModelCallRejected("model_provider_circuit_open")

    def _allocate_call_index(self) -> int:
        with self._health_lock:
            self._next_call_index += 1
            return self._next_call_index

    def _register_tail(self, call_index: int) -> None:
        del call_index
        with self._health_lock:
            self._active_tails += 1
            self._peak_tails = max(self._peak_tails, self._active_tails)
            if self._active_tails >= self._max_background_tails:
                if self._health_state != "circuit_open":
                    self._circuit_trips += 1
                self._health_state = "circuit_open"
            else:
                self._recompute_health_locked()

    def _complete_tail(
        self,
        call_index: int,
        *,
        completion_status: str,
        elapsed_seconds: float,
    ) -> None:
        with self._health_lock:
            self._active_tails = max(0, self._active_tails - 1)
            self._late_registry.append(
                {
                    "call_index": int(call_index),
                    "completion_status": str(completion_status),
                    "elapsed_seconds": round(
                        max(0.0, float(elapsed_seconds)),
                        6,
                    ),
                }
            )
            if len(self._late_registry) > self._late_registry_limit:
                del self._late_registry[
                    : len(self._late_registry) - self._late_registry_limit
                ]
            self._recompute_health_locked()

    def _recompute_health_locked(self) -> None:
        if self._active_tails >= self._max_background_tails:
            self._health_state = "circuit_open"
            return
        if self._active_tails:
            self._health_state = "degraded"
            return
        failures = sum(not outcome for outcome in self._health_window)
        window_size = len(self._health_window)
        if self._consecutive_failures >= 2 or (
            window_size >= 4 and failures >= 3 and failures * 2 >= window_size
        ):
            self._health_state = "degraded"
        else:
            self._health_state = "healthy"

    @staticmethod
    def _emit_timing(
        callback,
        *,
        queue_elapsed_seconds: float,
        agent_wait_seconds: float = 0.0,
        scheduler_wait_seconds: float = 0.0,
        rate_wait_seconds: float = 0.0,
        execution_elapsed_seconds: float,
        total_elapsed_seconds: float,
    ) -> None:
        if callback is None:
            return
        callback(
            {
                "queue_elapsed_seconds": round(
                    max(0.0, float(queue_elapsed_seconds)),
                    6,
                ),
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
                "execution_elapsed_seconds": round(
                    max(0.0, float(execution_elapsed_seconds)),
                    6,
                ),
                "total_elapsed_seconds": round(
                    max(0.0, float(total_elapsed_seconds)),
                    6,
                ),
            }
        )


class OfficialClientProvider:
    """Expose only the documented chat surface of the injected client."""

    def __init__(
        self,
        client: Any,
        gate: ModelCallGate,
        context_budget: ModelContextBudget | None = None,
        *,
        stage_execution_policy: (
            dict[str, dict[str, int | float]] | None
        ) = None,
        response_observer: Callable[[str, str], None] | None = None,
    ) -> None:
        if not callable(getattr(client, "chat", None)):
            raise TypeError("client must expose a callable chat method")
        self._chat = client.chat
        self._gate = gate
        self._stage_execution_policy = deepcopy(stage_execution_policy)
        self._response_observer = response_observer
        self._context_budget = context_budget or ModelContextBudget(
            context_window_tokens=262144,
            safety_margin_tokens=8192,
        )

    def chat(
        self,
        *,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        deadline: "DeadlineController | None" = None,
        budget: "CallBudget | None" = None,
        stage: str = "unallocated",
        turn_kind: str | None = None,
        agent_id: str | None = None,
        agent_action_protocol: bool = False,
        input_artifact_ids: tuple[str, ...] = (),
    ) -> str:
        active_turn_kind = turn_kind or stage
        protocol_runtime = budget.agent_runtime if budget is not None else None
        effective_max_tokens = effective_output_tokens(
            active_turn_kind,
            max_tokens,
            self._stage_execution_policy,
        )
        configured_stage_timeout = stage_call_timeout(
            active_turn_kind,
            self._stage_execution_policy,
        )
        minimum_start_window = stage_minimum_start_window(
            active_turn_kind,
            self._stage_execution_policy,
        )
        active_deadline = budget.deadline if budget is not None else deadline
        remaining_for_call = (
            active_deadline.remaining_for_model_call()
            if active_deadline is not None
            else configured_stage_timeout
        )
        effective_stage_timeout = effective_call_timeout(
            active_turn_kind,
            remaining_for_call,
            self._stage_execution_policy,
            client_timeout_seconds=PROVIDER_CALL_TIMEOUT_SECONDS,
        )
        effective_minimum_start_window = min(
            minimum_start_window,
            PROVIDER_CALL_TIMEOUT_SECONDS,
        )
        queue_budget = (
            feasible_queue_budget(
                active_turn_kind,
                active_deadline.remaining_for_model_call(),
                budget.model_queue_budget_seconds,
            )
            if budget is not None and active_deadline is not None
            else None
        )
        allocation = self._context_budget.allocate(
            messages,
            configured_max_output_tokens=effective_max_tokens,
        )
        try:
            protocol_turn = (
                protocol_runtime.begin_model_turn(
                    stage=stage,
                    turn_kind=active_turn_kind,
                    agent_hint=agent_id or "",
                    input_artifact_ids=tuple(input_artifact_ids),
                )
                if protocol_runtime is not None
                else None
            )
        except Exception:
            protocol_turn = None
        allocation_payload = {
            **allocation.to_dict(),
            "configured_output_tokens": max_tokens,
            "requested_max_output_tokens": max_tokens,
            "effective_output_tokens": allocation.max_output_tokens,
            "effective_max_output_tokens": allocation.max_output_tokens,
            "turn_kind": active_turn_kind,
            "action_category": ResourceGovernor.action_category_for_turn(
                stage,
                active_turn_kind,
            ),
            "stage_output_cap_tokens": stage_output_cap(
                active_turn_kind,
                self._stage_execution_policy,
            ),
            "configured_stage_timeout_seconds": configured_stage_timeout,
            "stage_timeout_seconds": configured_stage_timeout,
            "client_timeout_seconds": PROVIDER_CALL_TIMEOUT_SECONDS,
            "minimum_start_window_seconds": minimum_start_window,
            "effective_minimum_start_window_seconds": (
                effective_minimum_start_window
            ),
            "effective_stage_timeout_seconds": effective_stage_timeout,
            "transport_attempt_reservation": (
                self._gate.transport_attempt_reservation
            ),
            "transport_attempt_observability": "pending",
            "stage_p95_seconds": stage_p95_seconds(active_turn_kind),
            "effective_queue_budget_seconds": queue_budget,
            "agent_id": protocol_turn.agent_id if protocol_turn else (agent_id or ""),
            "agent_role": protocol_turn.role if protocol_turn else "",
            "agent_mode": protocol_turn.mode if protocol_turn else "",
            "task_id": protocol_turn.task_id if protocol_turn else "",
            "scheduler_task_id": protocol_turn.task_id if protocol_turn else "",
            "turn_id": protocol_turn.turn_id if protocol_turn else "",
            "plan_id": protocol_turn.plan_id if protocol_turn else "",
            "subgoal_ids": (
                list(protocol_turn.subgoal_ids) if protocol_turn else []
            ),
            "planned_method_family": (
                protocol_turn.method_family if protocol_turn else ""
            ),
        }
        call_index = (
            budget.record_model_call_started(stage, allocation_payload)
            if budget is not None
            else None
        )
        started = perf_counter()
        try:
            response = self._gate.call(
                self._chat,
                deadline=active_deadline,
                stage=stage,
                case_id=(budget.scheduler_case_id if budget is not None else ""),
                agent_id=(protocol_turn.agent_id if protocol_turn else (agent_id or active_turn_kind)),
                queue_budget_seconds=queue_budget,
                stage_timeout_seconds=effective_stage_timeout,
                minimum_start_window_seconds=(
                    effective_minimum_start_window
                    if budget is None
                    or budget.enforce_stage_start_window
                    else 0.0
                ),
                cancellation_token=(
                    budget.cancellation_token if budget is not None else None
                ),
                background_tail_callback=(
                    (
                        lambda event: budget.record_background_tail(
                            event,
                            call_index,
                        )
                    )
                    if budget is not None and call_index is not None
                    else None
                ),
                timing_callback=(
                    (
                        lambda timing: budget.record_model_call_timing(
                            call_index,
                            **timing,
                        )
                    )
                    if budget is not None and call_index is not None
                    else None
                ),
                dispatch_callback=(
                    (lambda: _record_protocol_dispatch(budget, call_index, protocol_runtime, protocol_turn))
                    if budget is not None and call_index is not None else None
                ),
                messages=messages,
                temperature=temperature,
                max_tokens=allocation.max_output_tokens,
            )
        except ModelCallRejected as error:
            _fail_protocol_turn(protocol_runtime, protocol_turn, error.code)
            if budget is not None and call_index is not None:
                if not error.dispatched:
                    budget.refund(stage=stage)
                if error.code != "model_response_deadline_exceeded":
                    budget.record_model_admission_rejection(error.code)
                if error.code == "model_response_deadline_exceeded":
                    budget.record_model_call_timeout(
                        call_index,
                        perf_counter() - started,
                        failure_code=error.code,
                    )
                else:
                    budget.record_model_call_failed(
                        call_index,
                        perf_counter() - started,
                        failure_code=error.code,
                    )
            raise
        except BudgetExceeded:
            _fail_protocol_turn(protocol_runtime, protocol_turn, "budget_exceeded")
            raise
        except Exception as error:
            failure_code = classify_transport_failure(error)
            _fail_protocol_turn(protocol_runtime, protocol_turn, failure_code)
            attempts, attempts_observed = transport_attempt_observation(error)
            self._gate.record_provider_result(
                success=False,
                failure_code=failure_code,
            )
            if budget is not None and call_index is not None:
                budget.record_model_call_lineage(
                    call_index,
                    {
                        "transport_attempt_observability": (
                            "observed"
                            if attempts_observed
                            else "reserved_upper_bound"
                        )
                    },
                )
                budget.record_model_call_failed(
                    call_index,
                    perf_counter() - started,
                    failure_code=failure_code,
                    transport_attempts=attempts,
                )
            raise ModelTransportError(
                failure_code,
                attempts=attempts,
            ) from error
        finally:
            if budget is not None:
                budget.record_provider_health(self._gate.health_snapshot())
        if not isinstance(response, str):
            _fail_protocol_turn(protocol_runtime, protocol_turn, "response_shape_invalid")
            self._gate.record_protocol_result(success=False)
            if budget is not None:
                budget.record_provider_health(self._gate.health_snapshot())
            if budget is not None and call_index is not None:
                budget.record_model_protocol_telemetry(
                    call_index,
                    "rejected",
                    "response_shape_invalid",
                    "hard_evidence_disabled",
                )
                budget.record_model_call_failed(
                    call_index,
                    perf_counter() - started,
                    failure_code="response_shape_invalid",
                )
            raise ModelTransportError("response_shape_invalid")
        attempts, attempts_observed = transport_attempt_observation(response)
        if budget is not None and call_index is not None:
            budget.record_model_call_lineage(
                call_index,
                {
                    "transport_attempt_observability": (
                        "observed" if attempts_observed else "reserved_upper_bound"
                    )
                },
            )
        if not response.strip():
            _fail_protocol_turn(protocol_runtime, protocol_turn, "empty_response")
            self._gate.record_provider_result(
                success=False,
                failure_code="empty_response",
            )
            if budget is not None:
                budget.record_provider_health(self._gate.health_snapshot())
            if budget is not None and call_index is not None:
                budget.record_model_call_failed(
                    call_index,
                    perf_counter() - started,
                    failure_code="empty_response",
                    transport_attempts=attempts,
                )
            raise ModelTransportError("empty_response", attempts=attempts)
        if self._response_observer is not None:
            try:
                self._response_observer(
                    budget.scheduler_case_id if budget is not None else "",
                    response,
                )
            except Exception:
                pass
        self._gate.record_provider_result(success=True)
        if budget is not None:
            budget.record_provider_health(self._gate.health_snapshot())
        output = self._context_budget.count_text(response)
        output_budget_exceeded = output.tokens > allocation.max_output_tokens
        finish_reason = str(
            getattr(response, "finish_reason", "unobservable")
        ) or "unobservable"
        if budget is not None and call_index is not None:
            budget.record_model_call_completed(
                call_index,
                observed_output_tokens=output.tokens,
                output_counting_mode=output.counting_mode,
                output_chars=len(response),
                elapsed_seconds=perf_counter() - started,
                transport_attempts=attempts,
                output_budget_exceeded=output_budget_exceeded,
                finish_reason=finish_reason,
            )
            if protocol_runtime is not None and protocol_turn is not None:
                if agent_action_protocol:
                    lineage = {
                        "agent_id": protocol_turn.agent_id,
                        "task_id": protocol_turn.task_id,
                        "turn_id": protocol_turn.turn_id,
                        "agent_protocol_status": "awaiting_domain_validation",
                    }
                else:
                    lineage = _complete_protocol_turn(
                        protocol_runtime,
                        protocol_turn,
                        response,
                    )
                budget.record_model_call_lineage(call_index, lineage)
            budget.record_tokens(output.tokens)
        if (
            allocation.prompt_tokens
            + output.tokens
            + allocation.safety_margin_tokens
            > allocation.context_window_tokens
        ):
            raise ContextBudgetExceeded(
                "model response exceeds the configured context window"
            )
        return ObservedModelResponse(
            response,
            transport_attempts=attempts,
            model_call_index=call_index,
            output_budget_exceeded=output_budget_exceeded,
            finish_reason=finish_reason,
            protocol_turn_id=(
                protocol_turn.turn_id if protocol_turn is not None else ""
            ),
        )
