from __future__ import annotations

from mathforge.context.claim_graph import ClaimGraph
from mathforge.harness.schemas import CandidateSolution, EvidenceRecord


def failed_claim_ids(candidate_id: str, evidence: list[EvidenceRecord]) -> list[str]:
    return sorted(
        {
            record.claim_id
            for record in evidence
            if record.candidate_id == candidate_id
            and record.claim_id is not None
            and record.status == "fail"
            and record.strength == "hard"
        }
    )


def repair_dependency_closure(
    candidate: CandidateSolution,
    evidence: list[EvidenceRecord],
) -> list[str]:
    return repair_impact_closure(candidate, evidence)


def repair_impact_closure(
    candidate: CandidateSolution,
    evidence: list[EvidenceRecord],
) -> list[str]:
    """Return failed claims, their prerequisites, and all downstream consumers."""
    affected = set(
        ClaimGraph(candidate.claims).dependency_closure(
            failed_claim_ids(candidate.candidate_id, evidence)
        )
    )
    changed = True
    while changed:
        changed = False
        for claim in candidate.claims:
            if claim.claim_id not in affected and affected.intersection(claim.depends_on):
                affected.add(claim.claim_id)
                changed = True
    return sorted(affected)
