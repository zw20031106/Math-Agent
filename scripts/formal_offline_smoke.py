from __future__ import annotations

import json
from pathlib import Path
import socket
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if (ROOT / "user_agent.py").is_file() and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _OfflineSocket(socket.socket):
    def connect(self, address: Any) -> None:
        del address
        raise AssertionError("runtime network access is forbidden")

    def connect_ex(self, address: Any) -> int:
        del address
        raise AssertionError("runtime network access is forbidden")


def _blocked_create_connection(*args: Any, **kwargs: Any) -> None:
    del args, kwargs
    raise AssertionError("runtime network access is forbidden")


socket.socket = _OfflineSocket  # type: ignore[misc]
socket.create_connection = _blocked_create_connection  # type: ignore[assignment]

from user_agent import ReasoningAgent  # noqa: E402


_STRICT_CANDIDATE = {
    "method": "direct-deduction",
    "final_answer": "2",
    "public_solution_steps": ["Evaluate the sum directly: 1+1=2."],
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


class OfflineOfficialClient:
    def chat(self, *, messages: Any, temperature: float, max_tokens: int) -> str:
        del messages, temperature, max_tokens
        return json.dumps(_STRICT_CANDIDATE, ensure_ascii=False)


def main() -> int:
    result = ReasoningAgent(OfflineOfficialClient()).solve(
        "Calculate the integer 1+1",
        {},
    )
    if result.get("status") != "success":
        raise AssertionError(f"formal offline smoke failed: {result!r}")
    if "2" not in str(result.get("final_response", "")):
        raise AssertionError("formal offline smoke returned the wrong answer")
    if not isinstance(result.get("trace"), list):
        raise AssertionError("formal offline smoke trace is invalid")
    print("Formal entry offline smoke passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
