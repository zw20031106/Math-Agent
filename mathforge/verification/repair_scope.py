from __future__ import annotations

from mathforge.context.claim_graph import ClaimGraph, namespaced_claim_id
from mathforge.harness.schemas import CandidateSolution, EvidenceRecord
from mathforge.verification.evidence import is_fatal_hard_failure


def failed_claim_ids(candidate_id: str, evidence: list[EvidenceRecord]) -> list[str]:
    return sorted(
        {
            record.claim_id
            for record in evidence
            if record.candidate_id == candidate_id
            and record.claim_id is not None
            and is_fatal_hard_failure(record)
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
    return claim_impact_closure(
        candidate,
        failed_claim_ids(candidate.candidate_id, evidence),
    )


def claim_impact_closure(
    candidate: CandidateSolution,
    root_claim_ids: list[str],
) -> list[str]:
    """Return the union of prerequisites and downstream consumers for roots."""
    graph = ClaimGraph.from_candidate(candidate)
    namespace_prefix = f"{candidate.candidate_id}::"
    affected = set(
        graph.dependency_closure(
            [
                namespaced_claim_id(candidate.candidate_id, claim_id)
                for claim_id in root_claim_ids
            ]
        )
    )
    changed = True
    while changed:
        changed = False
        for claim_id, dependencies in graph.nodes.items():
            if claim_id not in affected and affected.intersection(dependencies):
                affected.add(claim_id)
                changed = True
    return sorted(
        claim_id.removeprefix(namespace_prefix)
        for claim_id in affected
        if claim_id.startswith(namespace_prefix)
    )
