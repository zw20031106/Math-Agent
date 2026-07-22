from __future__ import annotations

from threading import BoundedSemaphore
from typing import Any


class ModelCallGate:
    """Bound concurrent access to the shared official client."""

    def __init__(self, max_concurrency: int) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        self._semaphore = BoundedSemaphore(max_concurrency)

    def call(self, function, /, **kwargs):
        with self._semaphore:
            return function(**kwargs)


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
    ) -> str:
        response = self._gate.call(
            self._chat,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if not isinstance(response, str):
            raise TypeError("client.chat must return a string")
        return response
