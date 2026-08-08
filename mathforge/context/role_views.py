from __future__ import annotations

from mathforge.context.assembler import ContextAssembler, RawContextStore
from mathforge.context.compressor import ContextCompressor
from mathforge.context.errors import ContextBudgetExceeded
from mathforge.context.snapshots import RoleContextView
from mathforge.harness.schemas import CandidateSolution, EvidenceRecord, ProblemIR, ProofObligation
from mathforge.memory.blackboard import MemoryBlackboard


class RoleContextFactory:
    """Build a role-filtered, budgeted view from session state and Blackboard grants."""

    def __init__(self, compressor: ContextCompressor | None = None) -> None:
        self._compressor = compressor or ContextCompressor()

    def build(
        self,
        *,
        problem: ProblemIR,
        candidates: list[CandidateSolution],
        evidence: list[EvidenceRecord],
        obligations: dict[str, list[ProofObligation]],
        blackboard: MemoryBlackboard,
        role: str,
        max_chars: int,
        focus_claim_ids: list[str] | None = None,
        final_answer: str = "",
        raw_store: RawContextStore | None = None,
        memory_categories: set[str] | frozenset[str] | None = None,
        public_metadata: dict | None = None,
    ) -> RoleContextView:
        assembler = ContextAssembler(raw_store or RawContextStore(max_chars))
        snapshot = assembler.assemble(
            problem,
            candidates,
            evidence,
            obligations,
            final_answer=final_answer,
        )
        snapshot.metadata["authorized_memory"] = blackboard.view(
            role,
            categories=memory_categories,
        )
        snapshot.metadata["public_metadata"] = dict(public_metadata or {})
        compressed = self._compressor.compress(
            snapshot,
            role=role,
            focus_claim_ids=focus_claim_ids,
            max_chars=max_chars,
        )
        view = RoleContextView(role, compressed.snapshot_id, compressed.to_dict(), max_chars)
        if view.char_count > max_chars:
            raise ContextBudgetExceeded(
                f"serialized {role} view exceeds budget: {view.char_count}>{max_chars}"
            )
        return view
