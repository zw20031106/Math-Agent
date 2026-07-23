from __future__ import annotations

from hashlib import sha256

from mathforge.context.claim_graph import namespaced_claim_id
from mathforge.harness.schemas import CandidateSolution, LemmaCard


class LemmaCurator:
    """Deterministic host-side Claim-to-Lemma transformation, not an LLM role."""

    def curate(
        self,
        candidates: list[CandidateSolution],
        *,
        round_id: int,
        excluded_statements: set[str] | None = None,
    ) -> list[LemmaCard]:
        excluded = excluded_statements or set()
        cards: list[LemmaCard] = []
        seen: set[str] = set()
        for candidate in candidates:
            for claim in candidate.claims:
                statement_key = " ".join(claim.statement.lower().split())
                if not statement_key or statement_key in seen or statement_key in excluded:
                    continue
                seen.add(statement_key)
                digest = sha256(statement_key.encode("utf-8")).hexdigest()[:12]
                dependencies = [
                    namespaced_claim_id(candidate.candidate_id, claim_id)
                    for claim_id in claim.depends_on
                ]
                card = LemmaCard(
                        lemma_id=(
                            f"{candidate.candidate_id}::lemma::{claim.claim_id}-{digest}"
                        ),
                        statement=claim.statement,
                        conditions=list(candidate.assumptions),
                        dependencies=dependencies,
                        proof_sketch=f"Extracted from {candidate.candidate_id}:{claim.claim_id}",
                        status="provisional",
                        evidence_ids=[],
                        source_round=round_id,
                        source_candidate_id=candidate.candidate_id,
                        source_claim_id=claim.claim_id,
                    )
                card.validate()
                cards.append(card)
        return cards
