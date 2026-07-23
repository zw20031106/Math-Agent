from __future__ import annotations

from mathforge.harness.schemas import CandidateSolution


def candidate_method_signature(candidate: CandidateSolution) -> tuple:
    """Describe actual structured work without trusting a free-text method label."""
    if candidate.method_steps:
        steps = tuple(
            (
                step.kind,
                "",
                tuple(sorted(step.claim_ids)),
                " ".join(step.theorem.strip().lower().split()),
            )
            for step in candidate.method_steps
        )
    else:
        steps = tuple(
            sorted(
                (
                    claim.claim_kind.strip().lower(),
                    claim.check_type.strip().lower(),
                    tuple(sorted(claim.depends_on)),
                    claim.importance.strip().lower(),
                )
                for claim in candidate.claims
            )
        )
    return (
        tuple(sorted(theorem.strip().lower() for theorem in candidate.theorems)),
        steps,
    )


def method_contract_valid(candidate: CandidateSolution) -> bool:
    return not any(
        deviation.startswith("method:")
        or deviation.startswith("method_steps")
        for deviation in candidate.contract_deviations
    )
