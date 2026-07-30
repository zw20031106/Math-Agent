from __future__ import annotations

from hashlib import sha256
import re

from mathforge.context.claim_graph import namespaced_claim_id
from mathforge.harness.schemas import (
    CandidateSolution,
    LemmaCard,
    ProofObligation,
)


_TOKEN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")


class LemmaCurator:
    """Deterministic host-side Claim-to-Lemma transformation, not an LLM role."""

    def curate(
        self,
        candidates: list[CandidateSolution],
        *,
        round_id: int,
        excluded_statements: set[str] | None = None,
        obligations: dict[str, list[ProofObligation]] | None = None,
        target: str = "",
    ) -> list[LemmaCard]:
        excluded = excluded_statements or set()
        unresolved = [
            obligation
            for items in (obligations or {}).values()
            for obligation in items
            if obligation.required and obligation.status != "satisfied"
        ]
        cards: list[LemmaCard] = []
        seen: set[str] = set()
        for candidate in candidates:
            for claim in candidate.claims:
                statement_key = " ".join(claim.statement.lower().split())
                if not statement_key or statement_key in seen or statement_key in excluded:
                    continue
                target_obligation_ids = _target_obligations(
                    claim.claim_id,
                    claim.claim_kind,
                    claim.statement,
                    unresolved,
                    target,
                )
                if (
                    (unresolved or target)
                    and not target_obligation_ids
                    and claim.importance != "critical"
                    and not _overlap(claim.statement, target)
                ):
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
                        proof_sketch=(
                            "Reuse the verified source Claim toward the named "
                            "problem-local target obligations."
                        ),
                        status="provisional",
                        evidence_ids=[],
                        source_round=round_id,
                        source_candidate_id=candidate.candidate_id,
                        source_claim_id=claim.claim_id,
                        claim_kind=claim.claim_kind,
                        check_spec=claim.check_spec,
                        target_obligation_ids=target_obligation_ids,
                    )
                card.validate()
                cards.append(card)
        return cards


def _target_obligations(
    claim_id: str,
    claim_kind: str,
    statement: str,
    obligations: list[ProofObligation],
    target: str,
) -> list[str]:
    scored: list[tuple[int, str]] = []
    for obligation in obligations:
        score = 0
        if claim_id in obligation.source_claim_ids:
            score += 100
        if claim_kind != "unknown" and claim_kind == obligation.kind:
            score += 40
        score += len(_overlap(statement, obligation.description))
        if score > 0:
            scored.append((score, obligation.obligation_id))
    scored.sort(key=lambda item: (-item[0], item[1]))
    if not scored and _overlap(statement, target) and obligations:
        scored.append((1, obligations[0].obligation_id))
    return [obligation_id for _, obligation_id in scored[:4]]


def _overlap(left: str, right: str) -> set[str]:
    if not left or not right:
        return set()
    return {
        item.casefold() for item in _TOKEN.findall(left)
    }.intersection(item.casefold() for item in _TOKEN.findall(right))
