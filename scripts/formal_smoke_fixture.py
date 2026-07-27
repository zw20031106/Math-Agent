from __future__ import annotations

import json
from typing import Any


_STRICT_CANDIDATE = {
    "method": "direct-deduction",
    "final_answer": "2",
    "public_solution_steps": [
        "Evaluate the sum directly: 1+1=2.",
    ],
    "claims": [
        {
            "claim_id": "c1",
            "statement": "1+1=2",
            "depends_on": [],
            "check_type": "symbolic_equivalence",
            "importance": "critical",
        }
    ],
    "method_steps": [
        {
            "step_id": "s1",
            "kind": "computation",
            "claim_ids": ["c1"],
            "theorem": "",
        }
    ],
    "solution_text": "Adding the two unit quantities gives 1+1=2.",
    "assumptions": [],
    "theorems": [],
    "unresolved_obligations": [],
}


class FormalSmokeClient:
    """Deterministic injected-client fixture for the formal entry contract."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def chat(self, *, messages, temperature, max_tokens) -> str:
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return json.dumps(_STRICT_CANDIDATE, ensure_ascii=False)


def assert_formal_smoke_result(result: dict[str, Any]) -> None:
    if set(result) != {"id", "status", "final_response", "trace"}:
        raise AssertionError("formal smoke result fields are invalid")
    if result.get("status") != "success":
        raise AssertionError("formal smoke did not reach success")
    if "2" not in str(result.get("final_response", "")):
        raise AssertionError("formal smoke final response does not contain the answer")
    trace = result.get("trace")
    if not isinstance(trace, list):
        raise AssertionError("formal smoke trace is not a list")
    if any(
        isinstance(event, dict)
        and (
            event.get("fallback_used") is True
            or "fallback" in str(event.get("event", "")).lower()
        )
        for event in trace
    ):
        raise AssertionError("formal smoke used fallback")
