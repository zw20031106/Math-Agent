from __future__ import annotations

from hashlib import sha256

from mathforge.harness.schemas import CandidateSolution, LemmaCard


class LemmaCurator:
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
            claims_by_id = {claim.claim_id: claim for claim in candidate.claims}
            for claim in candidate.claims:
                statement_key = " ".join(claim.statement.lower().split())
                if not statement_key or statement_key in seen or statement_key in excluded:
                    continue
                seen.add(statement_key)
                digest = sha256(statement_key.encode("utf-8")).hexdigest()[:12]
                dependencies = [
                    claims_by_id[claim_id].statement
                    for claim_id in claim.depends_on
                    if claim_id in claims_by_id
                ]
                cards.append(
                    LemmaCard(
                        lemma_id=f"lemma-{digest}",
                        statement=claim.statement,
                        conditions=list(candidate.assumptions),
                        dependencies=dependencies,
                        proof_sketch=f"Extracted from {candidate.candidate_id}:{claim.claim_id}",
                        status="provisional",
                        evidence_ids=[],
                        source_round=round_id,
                    )
                )
        return cards
