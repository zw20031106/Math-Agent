from __future__ import annotations

from threading import BoundedSemaphore, Event, Thread
from typing import Any, TYPE_CHECKING

from mathforge.harness.errors import BudgetExceeded

if TYPE_CHECKING:
    from mathforge.harness.deadline import DeadlineController


class ModelCallGate:
    """Bound concurrent access to the shared official client."""

    def __init__(self, max_concurrency: int) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        self._semaphore = BoundedSemaphore(max_concurrency)

    def call(self, function, /, *, deadline=None, **kwargs):
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

        def invoke() -> None:
            try:
                outcome["value"] = function(**kwargs)
            except BaseException as exc:
                outcome["error"] = exc
            finally:
                self._semaphore.release()
                done.set()

        Thread(
            target=invoke,
            name="mathforge-model-call",
            daemon=True,
        ).start()
        if not done.wait(deadline.remaining_for_model_call()):
            raise BudgetExceeded("model response exceeded deadline")
        if "error" in outcome:
            raise outcome["error"]
        return outcome.get("value")


class OfficialClientProvider:
    """Expose only the documented chat surface of the injected client."""

    def __init__(self, client: Any, gate: ModelCallGate) -> None:
        if not callable(getattr(client, "chat", None)):
            raise TypeError("client must expose a callable chat method")
        self._chat = client.chat
        self._gate = gate

    def chat(
        self,
        *,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        deadline: "DeadlineController | None" = None,
    ) -> str:
        response = self._gate.call(
            self._chat,
            deadline=deadline,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if not isinstance(response, str):
            raise TypeError("client.chat must return a string")
        return response
