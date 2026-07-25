from __future__ import annotations

from threading import BoundedSemaphore, Event, Lock, Thread
from time import perf_counter
from typing import Any, TYPE_CHECKING

from mathforge.context.errors import ContextBudgetExceeded
from mathforge.harness.context_budget import ModelContextBudget
from mathforge.harness.errors import BudgetExceeded

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
        if not done.wait(deadline.remaining_for_model_call()):
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
        allocation = self._context_budget.allocate(
            messages,
            configured_max_output_tokens=max_tokens,
        )
        call_index = (
            budget.record_model_call_started(stage, allocation.to_dict())
            if budget is not None
            else None
        )
        active_deadline = budget.deadline if budget is not None else deadline
        started = perf_counter()
        try:
            response = self._gate.call(
                self._chat,
                deadline=active_deadline,
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
                    )
                else:
                    budget.record_model_call_failed(
                        call_index,
                        perf_counter() - started,
                    )
            raise
        except BaseException:
            if budget is not None and call_index is not None:
                budget.record_model_call_failed(
                    call_index,
                    perf_counter() - started,
                )
            raise
        if not isinstance(response, str):
            if budget is not None and call_index is not None:
                budget.record_model_call_failed(
                    call_index,
                    perf_counter() - started,
                )
            raise TypeError("client.chat must return a string")
        output = self._context_budget.count_text(response)
        if budget is not None and call_index is not None:
            budget.record_model_call_completed(
                call_index,
                observed_output_tokens=output.tokens,
                output_counting_mode=output.counting_mode,
                output_chars=len(response),
                elapsed_seconds=perf_counter() - started,
            )
            budget.record_tokens(output.tokens)
        if output.tokens > allocation.max_output_tokens:
            raise ContextBudgetExceeded(
                "model response exceeds its dynamically allocated output budget"
            )
        return response
