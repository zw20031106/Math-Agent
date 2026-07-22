from __future__ import annotations

from hashlib import sha256
from uuid import uuid4

from mathforge.context.claim_graph import ClaimGraph
from mathforge.context.snapshots import ContextSnapshot
from mathforge.harness.schemas import CandidateSolution, EvidenceRecord, ProblemIR, ProofObligation


class RawContextStore:
    def __init__(self, max_chars: int) -> None:
        self._max_chars = max_chars
        self._contexts: dict[str, str] = {}

    def register(self, text: str) -> str:
        content = text[: self._max_chars]
        reference = f"raw:{sha256(content.encode('utf-8')).hexdigest()[:16]}"
        self._contexts.setdefault(reference, content)
        return reference

    def resolve(self, reference: str) -> str:
        return self._contexts[reference]


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
        all_claims = [claim for candidate in candidates for claim in candidate.claims]
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
            claim_graph=ClaimGraph(all_claims).to_dict(),
        )
