from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import combinations
from typing import Any

from mathforge.harness.schemas import CandidateSolution, ProofObligation
from mathforge.verification.answer_normalization import canonical_answer


@dataclass(frozen=True)
class CandidateReviewSummary:
    candidate_id: str
    source: str
    method: str
    final_answer: str
    answer_type: str
    public_solution_steps: tuple[str, ...]
    critical_claim_ids: tuple[str, ...]
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
            critical_claim_ids=tuple(
                claim.claim_id
                for claim in candidate.claims
                if claim.importance == "critical" and claim.statement.strip()
            ),
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
            "critical_claim_ids",
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
    critical_claim_conflict: bool

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
            answer_conflict = (
                left.answer_type != right.answer_type
                or canonical_answer(
                    left.final_answer,
                    left.answer_type,
                )
                != canonical_answer(
                    right.final_answer,
                    right.answer_type,
                )
            )
            conflicts.append(
                CandidateConflict(
                    left_candidate_id=left.candidate_id,
                    right_candidate_id=right.candidate_id,
                    answer_conflict=answer_conflict,
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
                    critical_claim_conflict=_critical_claims_conflict(
                        left.critical_claims,
                        right.critical_claims,
                        answer_conflict=answer_conflict,
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
            "review_targets": [
                item.to_dict()
                for item in self.review_targets()
            ],
        }

    def review_targets(self) -> tuple["ReviewTarget", ...]:
        targets: list[ReviewTarget] = []
        for conflict in self.conflicts:
            candidate_ids = (
                conflict.left_candidate_id,
                conflict.right_candidate_id,
            )
            if conflict.answer_conflict:
                targets.append(
                    ReviewTarget(
                        target_id=(
                            f"review:{conflict.left_candidate_id}:"
                            f"{conflict.right_candidate_id}:answer"
                        ),
                        level="answer",
                        candidate_ids=candidate_ids,
                        reason_codes=("answer_conflict",),
                    )
                )
            claim_reasons = tuple(
                reason
                for enabled, reason in (
                    (
                        conflict.assumption_conflict,
                        "assumption_conflict",
                    ),
                    (
                        conflict.critical_claim_conflict,
                        "critical_claim_conflict",
                    ),
                    (
                        conflict.obligation_conflict,
                        "obligation_conflict",
                    ),
                )
                if enabled
            )
            if claim_reasons:
                targets.append(
                    ReviewTarget(
                        target_id=(
                            f"review:{conflict.left_candidate_id}:"
                            f"{conflict.right_candidate_id}:claim"
                        ),
                        level="claim",
                        candidate_ids=candidate_ids,
                        reason_codes=claim_reasons,
                    )
                )
        return tuple(targets)


@dataclass(frozen=True)
class ReviewTarget:
    target_id: str
    level: str
    candidate_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "level": self.level,
            "candidate_ids": list(self.candidate_ids),
            "reason_codes": list(self.reason_codes),
        }


def candidate_review_segments(
    candidate: CandidateSolution,
) -> list[dict[str, Any]]:
    """Build bounded public, Claim-linked solution slices for verification."""

    valid_claim_ids = {
        claim.claim_id
        for claim in candidate.claims
    }
    fallback_claim_ids = [
        claim.claim_id
        for claim in candidate.claims
        if claim.importance == "critical"
    ] or [claim.claim_id for claim in candidate.claims]
    segments: list[dict[str, Any]] = []
    for index, text in enumerate(candidate.public_solution_steps[:64]):
        if not str(text).strip():
            continue
        method_claim_ids = (
            candidate.method_steps[index].claim_ids
            if index < len(candidate.method_steps)
            else []
        )
        claim_ids = [
            claim_id
            for claim_id in method_claim_ids
            if claim_id in valid_claim_ids
        ] or fallback_claim_ids[:4]
        segments.append(
            {
                "segment_id": (
                    f"{candidate.candidate_id}:public-step:{index + 1}"
                ),
                "claim_ids": list(dict.fromkeys(claim_ids)),
                "text": str(text).strip()[:3000],
            }
        )
    if not segments:
        for index, claim in enumerate(candidate.claims[:64]):
            if not claim.statement.strip():
                continue
            segments.append(
                {
                    "segment_id": (
                        f"{candidate.candidate_id}:claim:{index + 1}"
                    ),
                    "claim_ids": [claim.claim_id],
                    "text": claim.statement.strip()[:3000],
                }
            )
    return segments


def reviewable_obligation_ids(
    candidates: list[CandidateSolution],
    obligations: dict[str, list[ProofObligation]],
) -> tuple[str, ...]:
    candidate_claims = {
        candidate.candidate_id: {
            claim.claim_id
            for claim in candidate.claims
        }
        for candidate in candidates
    }
    return tuple(
        obligation.obligation_id
        for candidate in candidates
        for obligation in obligations.get(candidate.candidate_id, [])
        if obligation.required
        and set(obligation.source_claim_ids).intersection(
            candidate_claims.get(candidate.candidate_id, set())
        )
    )


def has_reviewable_work(
    candidates: list[CandidateSolution],
    obligations: dict[str, list[ProofObligation]],
    matrix: CandidateConflictMatrix,
) -> bool:
    return bool(
        reviewable_obligation_ids(candidates, obligations)
        or matrix.review_targets()
    )


def _normalized_set(values: tuple[str, ...]) -> set[str]:
    return {
        " ".join(value.casefold().split())
        for value in values
        if value.strip()
    }


def _critical_claims_conflict(
    left: tuple[str, ...],
    right: tuple[str, ...],
    *,
    answer_conflict: bool,
) -> bool:
    left_values = _normalized_set(left)
    right_values = _normalized_set(right)
    if answer_conflict:
        return left_values != right_values
    return any(
        _explicit_negation(left_value, right_value)
        for left_value in left_values
        for right_value in right_values
    )


def _explicit_negation(left: str, right: str) -> bool:
    prefixes = ("not ", "it is false that ", "不", "非", "并非")
    return any(
        left == f"{prefix}{right}" or right == f"{prefix}{left}"
        for prefix in prefixes
    )
