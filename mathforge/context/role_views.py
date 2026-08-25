from __future__ import annotations

from mathforge.context.assembler import ContextAssembler, RawContextStore
from mathforge.context.compressor import ContextCompressor
from mathforge.context.errors import ContextBudgetExceeded
from mathforge.context.snapshots import RoleContextView
from mathforge.harness.context_budget import InternS2TokenCounter
from mathforge.harness.schemas import CandidateSolution, EvidenceRecord, ProblemIR, ProofObligation
from mathforge.memory.blackboard import MemoryBlackboard


class RoleContextFactory:
    """Build a role-filtered, budgeted view from session state and Blackboard grants."""

    def __init__(
        self,
        compressor: ContextCompressor | None = None,
        token_counter: InternS2TokenCounter | None = None,
    ) -> None:
        self._compressor = compressor or ContextCompressor(token_counter=token_counter)

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
        max_tokens: int | None = None,
        core_token_budget: int | None = None,
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
            max_tokens=max_tokens,
            core_token_budget=core_token_budget,
        )
        view = RoleContextView(
            role,
            compressed.snapshot_id,
            compressed.to_dict(),
            max_chars,
            int(compressed.metadata.get("token_count", 0)),
            int(compressed.metadata.get("token_budget", 0)),
            int(compressed.metadata.get("core_token_count", 0)),
            int(compressed.metadata.get("core_token_budget", 0)),
        )
        if view.char_count > max_chars:
            raise ContextBudgetExceeded(
                f"serialized {role} view exceeds budget: {view.char_count}>{max_chars}"
            )
        return view
