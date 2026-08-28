from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from mathforge.harness.schemas import CandidateSolution, ProofObligation
from mathforge.verification.answer_normalization import canonical_answer
from mathforge.verification.e6 import (
    REPAIR_ACTIONS,
    RepairErrorCategory,
    classify_repair_error,
)


REPAIR_ACTION_BY_CATEGORY = {
    "local_arithmetic": "local_patch",
    "local_theorem_condition": "condition_repair",
    "representation_format": "re_encode",
    "global_method": "new_branch",
    "problem_interpretation": "replan",
}


@dataclass(frozen=True)
class ReviewTriggerDecision:
    should_run: bool
    bidirectional: bool
    candidate_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["candidate_ids"] = list(self.candidate_ids)
        payload["reason_codes"] = list(self.reason_codes)
        return payload


def decide_bidirectional_review(
    candidates: Iterable[CandidateSolution],
    *,
    risk_level: str = "medium",
    independent_candidate_ids: Iterable[str] = (),
) -> ReviewTriggerDecision:
    """Run a directed Solver review graph when independent branches add value."""

    items = [
        item
        for item in candidates
        if item.role in {"PrimarySolver", "AlternativeSolver"}
        and item.source.startswith("llm_")
    ]
    independent = set(independent_candidate_ids)
    if len(independent) >= 2:
        independent_items = [
            item for item in items if item.candidate_id in independent
        ]
        correlated_items = [
            item for item in items if item.candidate_id not in independent
        ]
        items = [*independent_items, *correlated_items]
    items = items[:3]
    candidate_ids = tuple(item.candidate_id for item in items)
    if len(items) < 2:
        return ReviewTriggerDecision(
            False,
            False,
            candidate_ids,
            ("fewer_than_two_independent_candidates",),
        )

    left, right = items[0], items[1]
    reasons: list[str] = []
    if canonical_answer(left.final_answer, left.answer_type) != canonical_answer(
        right.final_answer,
        right.answer_type,
    ):
        reasons.append("answer_disagreement")
    if (left.planned_method_family or left.method).casefold() != (
        right.planned_method_family or right.method
    ).casefold():
        reasons.append("method_diversity")
    if left.unresolved_obligations or right.unresolved_obligations:
        reasons.append("unresolved_obligations")
    if str(risk_level).casefold() == "high":
        reasons.append("high_risk")
    left_critical = {
        " ".join(claim.statement.casefold().split())
        for claim in left.claims
        if claim.importance == "critical"
    }
    right_critical = {
        " ".join(claim.statement.casefold().split())
        for claim in right.claims
        if claim.importance == "critical"
    }
    if left_critical != right_critical:
        reasons.append("critical_claim_divergence")
    if len(items) > 2:
        reasons.append("three_candidate_coverage")
        for extra in items[2:]:
            if canonical_answer(
                extra.final_answer,
                extra.answer_type,
            ) != canonical_answer(left.final_answer, left.answer_type):
                reasons.append("answer_disagreement")
            if (extra.planned_method_family or extra.method).casefold() != (
                left.planned_method_family or left.method
            ).casefold():
                reasons.append("method_diversity")
    return ReviewTriggerDecision(
        bool(reasons),
        bool(reasons),
        candidate_ids,
        tuple(dict.fromkeys(reasons or ["no_incremental_review_value"])),
    )


@dataclass(frozen=True)
class ConcessionDisposition:
    candidate_status: str
    reason_code: str
    requires_independent_confirmation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_concession(
    severity: str,
    *,
    scope: str = "local",
    confirmed: bool = False,
    independent_confirmation: bool | None = None,
) -> ConcessionDisposition:
    if independent_confirmation is not None:
        confirmed = bool(independent_confirmation)
    severity = str(severity).casefold().replace("_", "-")
    scope = str(scope).casefold()
    if severity == "critical" and scope == "global" and confirmed:
        return ConcessionDisposition(
            "rejected",
            "confirmed_global_critical",
            requires_independent_confirmation=False,
        )
    if severity == "critical":
        return ConcessionDisposition(
            "repair_requested",
            "critical_requires_independent_confirmation",
            requires_independent_confirmation=True,
        )
    if severity in {"error", "critical"}:
        return ConcessionDisposition("repair_requested", "local_error_conceded")
    return ConcessionDisposition("challenged", "nonfatal_finding_conceded")


@dataclass(frozen=True)
class RepairDirective:
    finding_id: str
    candidate_id: str
    category: str
    action: str
    claim_id: str = ""
    error_class: str = "LOCAL_ARITHMETIC"
    requires_independent_confirmation: bool = False

    def to_dict(self) -> dict[str, str]:
        payload = asdict(self)
        return payload

    @property
    def canonical_category(self) -> str:
        return self.error_class


def classify_repair_finding(finding: Any) -> RepairDirective:
    actionability = str(getattr(finding, "actionability", "")).casefold()
    scope = str(getattr(finding, "scope", "")).casefold()
    rationale = " ".join(
        str(value).casefold()
        for value in (
            getattr(finding, "public_rationale", ""),
            getattr(finding, "missing_condition", ""),
        )
    )
    error_class, canonical_action = classify_repair_error(
        finding,
        actionability=actionability,
        scope=scope,
        rationale=rationale,
        missing_condition=str(getattr(finding, "missing_condition", "")),
    )
    category_alias = {
        RepairErrorCategory.LOCAL_ARITHMETIC: "local_arithmetic",
        RepairErrorCategory.LOCAL_CONDITION: "local_theorem_condition",
        RepairErrorCategory.REPRESENTATION: "representation_format",
        RepairErrorCategory.GLOBAL_METHOD: "global_method",
        RepairErrorCategory.PROBLEM_INTERPRETATION: "problem_interpretation",
    }
    category = category_alias[error_class]
    return RepairDirective(
        finding_id=str(getattr(finding, "finding_id", "")),
        candidate_id=str(getattr(finding, "candidate_id", "")),
        category=category,
        action=REPAIR_ACTION_BY_CATEGORY[category],
        claim_id=str(getattr(finding, "claim_id", "")),
        error_class=error_class.value,
        requires_independent_confirmation=(
            str(getattr(finding, "severity", "")).casefold() == "critical"
        ),
    )


@dataclass(frozen=True)
class AuditRequirements:
    candidate_id: str
    candidate_version: int
    required_artifact_ids: tuple[str, ...]
    required_finding_ids: tuple[str, ...]
    required_obligation_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]

    @property
    def mandatory(self) -> bool:
        return bool(self.reason_codes)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for name in (
            "required_artifact_ids",
            "required_finding_ids",
            "required_obligation_ids",
            "reason_codes",
        ):
            payload[name] = list(payload[name])
        payload["mandatory"] = self.mandatory
        return payload


def build_audit_requirements(
    candidate: CandidateSolution,
    *,
    obligations: Iterable[ProofObligation] = (),
    finding_ids: Iterable[str] = (),
    artifact_ids: Iterable[str] = (),
    response_mode: str = "answer_only",
    risk_level: str = "medium",
    repaired: bool = False,
    unresolved_review_history: bool = False,
    low_support: bool = False,
) -> AuditRequirements:
    reasons: list[str] = []
    if str(response_mode) == "proof_full":
        reasons.append("proof")
    if repaired:
        reasons.append("repaired_candidate")
    if str(risk_level).casefold() == "high":
        reasons.append("high_risk")
    if unresolved_review_history:
        reasons.append("unresolved_review_history")
    if low_support:
        reasons.append("low_support")
    return AuditRequirements(
        candidate.candidate_id,
        int(candidate.version),
        tuple(dict.fromkeys(str(item) for item in artifact_ids if str(item))),
        tuple(dict.fromkeys(str(item) for item in finding_ids if str(item))),
        tuple(
            dict.fromkeys(
                item.obligation_id for item in obligations if bool(item.required)
            )
        ),
        tuple(reasons),
    )


__all__ = [
    "AuditRequirements",
    "ConcessionDisposition",
    "REPAIR_ACTION_BY_CATEGORY",
    "REPAIR_ACTIONS",
    "RepairErrorCategory",
    "RepairDirective",
    "ReviewTriggerDecision",
    "build_audit_requirements",
    "classify_concession",
    "classify_repair_finding",
    "classify_repair_error",
    "decide_bidirectional_review",
]
