from __future__ import annotations

from threading import BoundedSemaphore, Event, Lock, Thread
from time import perf_counter
from typing import Any, TYPE_CHECKING

from mathforge.context.errors import ContextBudgetExceeded
from mathforge.harness.context_budget import ModelContextBudget
from mathforge.harness.errors import BudgetExceeded
from mathforge.harness.errors import ModelTransportError
from mathforge.harness.model_policy import (
    effective_call_timeout,
    effective_output_tokens,
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

    def __init__(self, max_concurrency: int) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        self._semaphore = BoundedSemaphore(max_concurrency)

    def call(
        self,
        function,
        /,
        *,
        deadline=None,
        background_tail_callback=None,
        stage: str = "unallocated",
        **kwargs,
    ):
        if deadline is None:
            with self._semaphore:
                return function(**kwargs)
        timeout = deadline.remaining_for_model_call()
        if timeout <= 0 or not self._semaphore.acquire(timeout=timeout):
            raise BudgetExceeded("model concurrency wait exceeded deadline")
        if not deadline.can_start_model_call():
            self._semaphore.release()
            raise BudgetExceeded("model call deadline reached")

        done = Event()
        outcome: dict[str, Any] = {}
        state_lock = Lock()
        state = {"completed": False, "timed_out": False}

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
                if is_background_tail and background_tail_callback is not None:
                    background_tail_callback("completed")

        Thread(
            target=invoke,
            name="mathforge-model-call",
            daemon=True,
        ).start()
        if not done.wait(
            effective_call_timeout(stage, deadline.remaining_for_model_call())
        ):
            with state_lock:
                state["timed_out"] = True
                already_completed = state["completed"]
                if background_tail_callback is not None:
                    background_tail_callback("started")
            if already_completed and background_tail_callback is not None:
                background_tail_callback("completed")
            raise BudgetExceeded("model response exceeded deadline")
        if "error" in outcome:
            raise outcome["error"]
        return outcome.get("value")


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
                background_tail_callback=(
                    budget.record_background_tail
                    if budget is not None
                    else None
                ),
                messages=messages,
                temperature=temperature,
                max_tokens=allocation.max_output_tokens,
            )
        except BudgetExceeded as error:
            if budget is not None and call_index is not None:
                if "response exceeded" in str(error):
                    budget.record_model_call_timeout(
                        call_index,
                        perf_counter() - started,
                        failure_code="model_response_deadline_exceeded",
                    )
                else:
                    budget.record_model_call_failed(
                        call_index,
                        perf_counter() - started,
                        failure_code="model_concurrency_wait_exceeded",
                    )
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
