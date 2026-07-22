from __future__ import annotations

from mathforge.harness.schemas import CandidateSolution


def candidate_method_signature(candidate: CandidateSolution) -> tuple:
    """Describe the method actually returned, never the preassigned label alone."""
    topology = tuple(
        sorted(
            (claim.check_type.strip().lower(), len(claim.depends_on), claim.importance.strip().lower())
            for claim in candidate.claims
        )
    )
    return (
        " ".join(candidate.method.strip().lower().split()),
        tuple(sorted(theorem.strip().lower() for theorem in candidate.theorems)),
        topology,
    )
