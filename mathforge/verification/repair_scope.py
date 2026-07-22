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
    return ClaimGraph(candidate.claims).dependency_closure(
        failed_claim_ids(candidate.candidate_id, evidence)
    )
