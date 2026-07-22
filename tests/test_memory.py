from __future__ import annotations

import pytest

from mathforge.memory.blackboard import MemoryBlackboard
from mathforge.memory.session_memory import SessionMemory


def test_blackboard_enforces_agent_permissions():
    memory = SessionMemory()
    board = MemoryBlackboard(memory)
    board.publish("System", "raw", {"problem": "p"})
    board.publish("PrimarySolver", "working", {"full_solution": "secret"})
    alternative = board.view("AlternativeSolver")
    assert [item["category"] for item in alternative] == ["raw"]
    with pytest.raises(PermissionError):
        board.publish("AlternativeSolver", "evidence", {})


def test_session_memory_isolation_and_release():
    first = SessionMemory()
    second = SessionMemory()
    first.add("working", {"answer": 1}, "PrimarySolver")
    assert second.to_dict() == {"items": []}
    first.clear()
    assert first.to_dict() == {"items": []}
