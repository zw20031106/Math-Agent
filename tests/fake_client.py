from __future__ import annotations

import re
import threading
import time


class FakeClient:
    def __init__(self, *, fail: bool = False, delay: float = 0.0) -> None:
        self.fail = fail
        self.delay = delay
        self.calls: list[dict] = []
        self._lock = threading.Lock()
        self.active_calls = 0
        self.max_active_calls = 0

    def chat(self, *, messages, temperature, max_tokens) -> str:
        with self._lock:
            self.active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self.active_calls)
            self.calls.append(
                {
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
            )
        try:
            if self.delay:
                time.sleep(self.delay)
            if self.fail:
                raise RuntimeError("simulated provider failure")
            user_content = messages[-1]["content"]
            match = re.search(r"Problem:\n(.*?)\n\nProvide", user_content, re.DOTALL)
            problem = match.group(1) if match else user_content
            return f"Solved independently: {problem}"
        finally:
            with self._lock:
                self.active_calls -= 1
