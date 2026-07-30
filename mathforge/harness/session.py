from __future__ import annotations

from uuid import uuid4

from mathforge.harness.budget import CallBudget
from mathforge.harness.schemas import MathSession


def create_session(
    problem: str,
    metadata: dict,
    budget: CallBudget,
    *,
    raw_context_max_chars: int = 48000,
) -> MathSession:
    from mathforge.context.assembler import RawContextStore
    from mathforge.memory.session_memory import SessionMemory
    from mathforge.memory.lemma_memory import LemmaMemory

    memory = SessionMemory()
    session_id = uuid4().hex
    budget.bind_scheduler_case(session_id)
    return MathSession(
        session_id=session_id,
        problem=problem,
        metadata=dict(metadata),
        budget=budget,
        working_memory=memory,
        lemma_memory=LemmaMemory(memory),
        raw_context_store=RawContextStore(raw_context_max_chars),
    )
