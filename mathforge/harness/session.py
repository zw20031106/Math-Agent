from __future__ import annotations

from uuid import uuid4

from mathforge.harness.budget import CallBudget
from mathforge.harness.schemas import MathSession


def create_session(problem: str, metadata: dict, budget: CallBudget) -> MathSession:
    from mathforge.memory.session_memory import SessionMemory

    return MathSession(
        session_id=uuid4().hex,
        problem=problem,
        metadata=dict(metadata),
        budget=budget,
        working_memory=SessionMemory(),
    )
