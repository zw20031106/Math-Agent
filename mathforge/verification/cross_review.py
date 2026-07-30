from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import combinations

from mathforge.harness.schemas import CandidateSolution
from mathforge.verification.answer_normalization import canonical_answer


@dataclass(frozen=True)
class CandidateReviewSummary:
    candidate_id: str
    source: str
    method: str
    final_answer: str
    answer_type: str
    public_solution_steps: tuple[str, ...]
    critical_claims: tuple[str, ...]
    assumptions: tuple[str, ...]
    unresolved_obligations: tuple[str, ...]

    @classmethod
    def from_candidate(
        cls,
        candidate: CandidateSolution,
    ) -> "CandidateReviewSummary":
        return cls(
            candidate_id=candidate.candidate_id,
            source=candidate.source,
            method=candidate.method,
            final_answer=candidate.final_answer,
            answer_type=candidate.answer_type,
            public_solution_steps=tuple(candidate.public_solution_steps),
            critical_claims=tuple(
                claim.statement
                for claim in candidate.claims
                if claim.importance == "critical" and claim.statement.strip()
            ),
            assumptions=tuple(candidate.assumptions),
            unresolved_obligations=tuple(candidate.unresolved_obligations),
        )

    def to_dict(self) -> dict:
        payload = asdict(self)
        for name in (
            "public_solution_steps",
            "critical_claims",
            "assumptions",
            "unresolved_obligations",
        ):
            payload[name] = list(payload[name])
        return payload


@dataclass(frozen=True)
class CandidateConflict:
    left_candidate_id: str
    right_candidate_id: str
    answer_conflict: bool
    method_conflict: bool
    assumption_conflict: bool
    obligation_conflict: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CandidateConflictMatrix:
    candidate_ids: tuple[str, ...]
    conflicts: tuple[CandidateConflict, ...]

    @classmethod
    def build(
        cls,
        summaries: list[CandidateReviewSummary],
    ) -> "CandidateConflictMatrix":
        ordered = sorted(summaries, key=lambda item: item.candidate_id)
        conflicts = []
        for left, right in combinations(ordered, 2):
            conflicts.append(
                CandidateConflict(
                    left_candidate_id=left.candidate_id,
                    right_candidate_id=right.candidate_id,
                    answer_conflict=(
                        left.answer_type != right.answer_type
                        or canonical_answer(
                            left.final_answer,
                            left.answer_type,
                        )
                        != canonical_answer(
                            right.final_answer,
                            right.answer_type,
                        )
                    ),
                    method_conflict=(
                        left.method.strip().lower()
                        != right.method.strip().lower()
                    ),
                    assumption_conflict=(
                        set(left.assumptions) != set(right.assumptions)
                    ),
                    obligation_conflict=(
                        set(left.unresolved_obligations)
                        != set(right.unresolved_obligations)
                    ),
                )
            )
        return cls(
            candidate_ids=tuple(item.candidate_id for item in ordered),
            conflicts=tuple(conflicts),
        )

    def to_dict(self) -> dict:
        return {
            "candidate_ids": list(self.candidate_ids),
            "conflicts": [item.to_dict() for item in self.conflicts],
        }
