from __future__ import annotations

from copy import deepcopy
from threading import BoundedSemaphore, Event, Lock, Thread
from time import perf_counter
from typing import Any, TYPE_CHECKING

from mathforge.context.errors import ContextBudgetExceeded
from mathforge.harness.context_budget import ModelContextBudget
from mathforge.harness.errors import BudgetExceeded
from mathforge.harness.errors import ModelCallRejected
from mathforge.harness.errors import ModelTransportError
from mathforge.harness.model_policy import (
    effective_output_tokens,
    stage_call_timeout,
    stage_output_cap,
)
from mathforge.harness.transport import (
    ObservedModelResponse,
    classify_transport_failure,
    transport_attempts,
)

if TYPE_CHECKING:
    from mathforge.harness.budget import CallBudget
    from mathforge.harness.deadline import DeadlineController


class ModelCallGate:
    """Bound concurrent access to the shared official client."""

    def __init__(
        self,
        max_concurrency: int,
        *,
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
        self._semaphore = BoundedSemaphore(max_concurrency)
        self._max_background_tails = tail_limit
        self._late_registry_limit = int(late_registry_limit)
        self._health_lock = Lock()
        self._health_state = "healthy"
        self._active_tails = 0
        self._peak_tails = 0
        self._circuit_trips = 0
        self._fast_failures = 0
        self._next_call_index = 0
        self._late_registry: list[dict[str, Any]] = []

    def call(
        self,
        function,
        /,
        *,
        deadline=None,
        background_tail_callback=None,
        stage: str = "unallocated",
        queue_budget_seconds: float | None = None,
        stage_timeout_seconds: float | None = None,
        timing_callback=None,
        **kwargs,
    ):
        if deadline is None:
            self._reject_open_circuit(timing_callback)
            with self._semaphore:
                return function(**kwargs)

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
            min(
                stage_timeout,
                queue_budget,
                deadline.remaining_for_model_call(),
            ),
        )
        if acquire_timeout <= 0 or not self._semaphore.acquire(
            timeout=acquire_timeout
        ):
            queue_elapsed = perf_counter() - started
            self._emit_timing(
                timing_callback,
                queue_elapsed_seconds=queue_elapsed,
                execution_elapsed_seconds=0.0,
                total_elapsed_seconds=queue_elapsed,
            )
            raise ModelCallRejected("model_concurrency_wait_exceeded")
        queue_elapsed = perf_counter() - started
        try:
            self._reject_open_circuit(timing_callback, queue_elapsed)
        except ModelCallRejected:
            self._semaphore.release()
            raise
        if not deadline.can_start_model_call():
            self._semaphore.release()
            self._emit_timing(
                timing_callback,
                queue_elapsed_seconds=queue_elapsed,
                execution_elapsed_seconds=0.0,
                total_elapsed_seconds=queue_elapsed,
            )
            raise ModelCallRejected("model_response_deadline_exceeded")

        execution_timeout = max(
            0.0,
            min(
                stage_timeout - queue_elapsed,
                deadline.remaining_for_model_call(),
            ),
        )
        if execution_timeout <= 0:
            self._semaphore.release()
            self._emit_timing(
                timing_callback,
                queue_elapsed_seconds=queue_elapsed,
                execution_elapsed_seconds=0.0,
                total_elapsed_seconds=queue_elapsed,
            )
            raise ModelCallRejected("model_concurrency_wait_exceeded")

        done = Event()
        outcome: dict[str, Any] = {}
        state_lock = Lock()
        state = {"completed": False, "timed_out": False}
        execution_started = perf_counter()
        call_index = self._allocate_call_index()

        def invoke() -> None:
            try:
                outcome["value"] = function(**kwargs)
            except BaseException as exc:
                outcome["error"] = exc
            finally:
                with state_lock:
                    state["completed"] = True
                    is_background_tail = state["timed_out"]
                self._semaphore.release()
                done.set()
                if is_background_tail:
                    self._complete_tail(
                        call_index,
                        completion_status=(
                            "failed" if "error" in outcome else "completed"
                        ),
                        elapsed_seconds=perf_counter() - execution_started,
                    )

        Thread(
            target=invoke,
            name="mathforge-model-call",
            daemon=True,
        ).start()
        if not done.wait(execution_timeout):
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
                    execution_elapsed_seconds=execution_elapsed,
                    total_elapsed_seconds=perf_counter() - started,
                )
                raise ModelCallRejected("model_response_deadline_exceeded")
        execution_elapsed = perf_counter() - execution_started
        self._emit_timing(
            timing_callback,
            queue_elapsed_seconds=queue_elapsed,
            execution_elapsed_seconds=execution_elapsed,
            total_elapsed_seconds=perf_counter() - started,
        )
        if "error" in outcome:
            raise outcome["error"]
        return outcome.get("value")

    def health_snapshot(self) -> dict[str, Any]:
        with self._health_lock:
            return {
                "state": self._health_state,
                "active_tails": self._active_tails,
                "peak_tails": self._peak_tails,
                "circuit_trips": self._circuit_trips,
                "fast_failures": self._fast_failures,
                "late_registry": deepcopy(self._late_registry),
            }

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
                self._health_state = "degraded"

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
            self._health_state = (
                "healthy" if self._active_tails == 0 else "degraded"
            )

    @staticmethod
    def _emit_timing(
        callback,
        *,
        queue_elapsed_seconds: float,
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
    ) -> None:
        if not callable(getattr(client, "chat", None)):
            raise TypeError("client must expose a callable chat method")
        self._chat = client.chat
        self._gate = gate
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
    ) -> str:
        effective_max_tokens = effective_output_tokens(stage, max_tokens)
        allocation = self._context_budget.allocate(
            messages,
            configured_max_output_tokens=effective_max_tokens,
        )
        allocation_payload = {
            **allocation.to_dict(),
            "configured_output_tokens": max_tokens,
            "stage_output_cap_tokens": stage_output_cap(stage),
        }
        call_index = (
            budget.record_model_call_started(stage, allocation_payload)
            if budget is not None
            else None
        )
        active_deadline = budget.deadline if budget is not None else deadline
        started = perf_counter()
        try:
            response = self._gate.call(
                self._chat,
                deadline=active_deadline,
                stage=stage,
                queue_budget_seconds=(
                    budget.model_queue_budget_seconds
                    if budget is not None
                    else None
                ),
                background_tail_callback=(
                    budget.record_background_tail
                    if budget is not None
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
                messages=messages,
                temperature=temperature,
                max_tokens=allocation.max_output_tokens,
            )
        except ModelCallRejected as error:
            if budget is not None and call_index is not None:
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
            raise
        except Exception as error:
            failure_code = classify_transport_failure(error)
            attempts = transport_attempts(error)
            if budget is not None and call_index is not None:
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
            if budget is not None and call_index is not None:
                budget.record_model_call_failed(
                    call_index,
                    perf_counter() - started,
                    failure_code="response_shape_invalid",
                )
            raise ModelTransportError("response_shape_invalid")
        attempts = transport_attempts(response)
        if not response.strip():
            if budget is not None and call_index is not None:
                budget.record_model_call_failed(
                    call_index,
                    perf_counter() - started,
                    failure_code="empty_response",
                    transport_attempts=attempts,
                )
            raise ModelTransportError("empty_response", attempts=attempts)
        output = self._context_budget.count_text(response)
        if budget is not None and call_index is not None:
            budget.record_model_call_completed(
                call_index,
                observed_output_tokens=output.tokens,
                output_counting_mode=output.counting_mode,
                output_chars=len(response),
                elapsed_seconds=perf_counter() - started,
                transport_attempts=attempts,
            )
            budget.record_tokens(output.tokens)
        if output.tokens > allocation.max_output_tokens:
            raise ContextBudgetExceeded(
                "model response exceeds its dynamically allocated output budget"
            )
        return ObservedModelResponse(
            response,
            transport_attempts=attempts,
            model_call_index=call_index,
        )
