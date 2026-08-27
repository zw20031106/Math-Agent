from __future__ import annotations

from hashlib import sha256
from uuid import uuid4

from mathforge.context.claim_graph import ClaimGraph
from mathforge.context.errors import ContextBudgetExceeded
from mathforge.context.snapshots import ContextSnapshot
from mathforge.harness.problem_conditions import build_problem_condition_envelope
from mathforge.harness.schemas import CandidateSolution, EvidenceRecord, ProblemIR, ProofObligation


class RawContextStore:
    def __init__(self, max_chars: int) -> None:
        if max_chars < 1:
            raise ValueError("raw context capacity must be positive")
        self._max_chars = max_chars
        self._contexts: dict[str, str] = {}

    def register(self, text: str) -> str:
        content = str(text)
        reference = f"raw:{sha256(content.encode('utf-8')).hexdigest()[:16]}"
        existing = self._contexts.get(reference)
        if existing is not None:
            if existing != content:
                raise ContextBudgetExceeded("raw context digest collision")
            return reference
        if self.stored_chars + len(content) > self._max_chars:
            raise ContextBudgetExceeded("raw context store capacity exceeded")
        self._contexts[reference] = content
        return reference

    def resolve(self, reference: str) -> str:
        return self._contexts[reference]

    @property
    def stored_chars(self) -> int:
        return sum(len(value) for value in self._contexts.values())


class ContextAssembler:
    def __init__(self, raw_store: RawContextStore | None = None) -> None:
        self._raw_store = raw_store or RawContextStore(48000)

    def assemble(
        self,
        problem: ProblemIR,
        candidates: list[CandidateSolution],
        evidence: list[EvidenceRecord],
        obligations: dict[str, list[ProofObligation]],
        *,
        final_answer: str = "",
    ) -> ContextSnapshot:
        reference = self._raw_store.register(problem.raw_problem)
        condition_envelope = build_problem_condition_envelope(problem)
        return ContextSnapshot(
            snapshot_id=f"ctx-{uuid4().hex[:12]}",
            raw_context_ref=reference,
            original_problem=problem.raw_problem,
            conditions=list(problem.assumptions),
            final_answer=final_answer,
            candidates=[candidate.to_dict() for candidate in candidates],
            evidence=[record.to_dict() for record in evidence],
            obligations=[
                obligation.to_dict()
                for items in obligations.values()
                for obligation in items
            ],
            claim_graph=ClaimGraph.from_candidates(candidates).to_nodes_dict(),
            metadata={
                "problem_condition_envelope": condition_envelope.to_dict(
                    include_target=False
                ),
            },
        )
