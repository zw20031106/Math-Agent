from __future__ import annotations

import json
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
            match = re.search(
                r"Problem:\n(.*?)(?:\n\nRequired core method family:|\n\nProvide)",
                user_content,
                re.DOTALL,
            )
            problem = match.group(1) if match else user_content
            method_match = re.search(
                r"Required core method family: ([a-z-]+)\.",
                user_content,
            )
            method = method_match.group(1) if method_match else "direct-deduction"
            return json.dumps(
                {
                    "method": method,
                    "final_answer": problem,
                    "public_solution_steps": [
                        f"Solved independently: {problem}"
                    ],
                    "claims": [
                        {
                            "claim_id": "c1",
                            "statement": f"The requested result is {problem}.",
                            "depends_on": [],
                            "check_type": "reasoning",
                            "importance": "critical",
                        }
                    ],
                    "method_steps": [
                        {
                            "step_id": "s1",
                            "kind": "conclusion",
                            "claim_ids": ["c1"],
                            "theorem": "",
                        }
                    ],
                    "solution_text": f"Solved independently: {problem}",
                    "assumptions": [],
                    "theorems": [],
                    "unresolved_obligations": [],
                },
                ensure_ascii=False,
            )
        finally:
            with self._lock:
                self.active_calls -= 1
