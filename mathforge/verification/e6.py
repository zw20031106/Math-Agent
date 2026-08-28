"""E6 verification, repair and arbitration policy primitives.

The E6 plan makes a distinction that is easy to lose in a large harness:
``not_disproved`` is a negative result, while ``hard_verified`` is a positive
evidence result.  This module keeps that distinction in small, deterministic
data objects so the runtime, completion gate and arbitration layer can share
the same vocabulary without making another model call.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import re
from typing import Any, Iterable, Mapping

from mathforge.verification.answer_normalization import (
    answer_shape_valid,
    canonical_answer,
)


class EvidenceStatus(str, Enum):
    """Canonical E6 status for tool and verifier evidence."""

    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    UNSUPPORTED = "UNSUPPORTED"
    MALFORMED = "MALFORMED"
    TIMEOUT = "TIMEOUT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class RepairErrorCategory(str, Enum):
    """Host-owned repair taxonomy from the E6 plan."""

    LOCAL_ARITHMETIC = "LOCAL_ARITHMETIC"
    LOCAL_CONDITION = "LOCAL_CONDITION"
    REPRESENTATION = "REPRESENTATION"
    GLOBAL_METHOD = "GLOBAL_METHOD"
    PROBLEM_INTERPRETATION = "PROBLEM_INTERPRETATION"


REPAIR_ACTIONS = {
    RepairErrorCategory.LOCAL_ARITHMETIC: "local_patch",
    RepairErrorCategory.LOCAL_CONDITION: "condition_repair",
    RepairErrorCategory.REPRESENTATION: "re_encode",
    RepairErrorCategory.GLOBAL_METHOD: "new_branch",
    RepairErrorCategory.PROBLEM_INTERPRETATION: "replan",
}


def normalize_repair_category(value: Any) -> RepairErrorCategory:
    text = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    aliases = {
        "local_arithmetic": RepairErrorCategory.LOCAL_ARITHMETIC,
        "arithmetic": RepairErrorCategory.LOCAL_ARITHMETIC,
        "local_theorem_condition": RepairErrorCategory.LOCAL_CONDITION,
        "local_condition": RepairErrorCategory.LOCAL_CONDITION,
        "condition": RepairErrorCategory.LOCAL_CONDITION,
        "representation_format": RepairErrorCategory.REPRESENTATION,
        "representation": RepairErrorCategory.REPRESENTATION,
        "format": RepairErrorCategory.REPRESENTATION,
        "global_method": RepairErrorCategory.GLOBAL_METHOD,
        "method": RepairErrorCategory.GLOBAL_METHOD,
        "problem_interpretation": RepairErrorCategory.PROBLEM_INTERPRETATION,
        "interpretation": RepairErrorCategory.PROBLEM_INTERPRETATION,
        "replan": RepairErrorCategory.PROBLEM_INTERPRETATION,
    }
    try:
        return RepairErrorCategory[text.upper()]
    except KeyError:
        return aliases.get(text, RepairErrorCategory.LOCAL_ARITHMETIC)


def classify_repair_error(
    finding: Any = None,
    *,
    actionability: str = "",
    scope: str = "",
    rationale: str = "",
    missing_condition: str = "",
) -> tuple[RepairErrorCategory, str]:
    """Classify a review finding and return its deterministic repair action."""

    if finding is not None:
        actionability = str(getattr(finding, "actionability", actionability))
        scope = str(getattr(finding, "scope", scope))
        rationale = " ".join(
            (
                str(getattr(finding, "public_rationale", rationale)),
                str(getattr(finding, "missing_condition", missing_condition)),
            )
        )
    action = str(actionability).casefold()
    scope_value = str(scope).casefold()
    text = str(rationale).casefold()
    if action == "replan":
        category = RepairErrorCategory.PROBLEM_INTERPRETATION
    elif action == "new_branch" or scope_value == "global":
        category = RepairErrorCategory.GLOBAL_METHOD
    elif any(token in text for token in ("format", "represent", "encode", "schema")):
        category = RepairErrorCategory.REPRESENTATION
    elif str(missing_condition).strip() or "condition" in text:
        category = RepairErrorCategory.LOCAL_CONDITION
    else:
        category = RepairErrorCategory.LOCAL_ARITHMETIC
    return category, REPAIR_ACTIONS[category]


_EVIDENCE_STATUS_ALIASES = {
    "pass": EvidenceStatus.PASS,
    "passed": EvidenceStatus.PASS,
    "success": EvidenceStatus.PASS,
    "ok": EvidenceStatus.PASS,
    "fail": EvidenceStatus.FAIL,
    "failed": EvidenceStatus.FAIL,
    "reject": EvidenceStatus.FAIL,
    "rejected": EvidenceStatus.FAIL,
    "unknown": EvidenceStatus.UNKNOWN,
    "unresolved": EvidenceStatus.UNKNOWN,
    "unsupported": EvidenceStatus.UNSUPPORTED,
    "not_supported": EvidenceStatus.UNSUPPORTED,
    "not-supported": EvidenceStatus.UNSUPPORTED,
    "malformed": EvidenceStatus.MALFORMED,
    "invalid": EvidenceStatus.MALFORMED,
    "parse_error": EvidenceStatus.MALFORMED,
    "schema_invalid": EvidenceStatus.MALFORMED,
    "timeout": EvidenceStatus.TIMEOUT,
    "timed_out": EvidenceStatus.TIMEOUT,
    "deadline": EvidenceStatus.TIMEOUT,
    "error": EvidenceStatus.INTERNAL_ERROR,
    "internal_error": EvidenceStatus.INTERNAL_ERROR,
    "exception": EvidenceStatus.INTERNAL_ERROR,
    "transport_error": EvidenceStatus.INTERNAL_ERROR,
}


def normalize_evidence_status(status: Any, *, reason: Any = "") -> EvidenceStatus:
    """Normalize legacy lower-case tool statuses to the E6 taxonomy.

    The wire-compatible ``EvidenceRecord.status`` remains unchanged.  This
    function is deliberately side-effect free and is therefore safe for old
    records as well as newly emitted records.
    """

    value = str(status or "").strip().casefold().replace(" ", "_")
    reason_text = str(reason or "").casefold()
    if "timeout" in value or "timed out" in reason_text:
        return EvidenceStatus.TIMEOUT
    if "unsupported" in value or "not supported" in reason_text:
        return EvidenceStatus.UNSUPPORTED
    if "malform" in value or "parse" in reason_text or "schema" in reason_text:
        return EvidenceStatus.MALFORMED
    if value in _EVIDENCE_STATUS_ALIASES:
        return _EVIDENCE_STATUS_ALIASES[value]
    if "error" in value or "exception" in reason_text:
        return EvidenceStatus.INTERNAL_ERROR
    return EvidenceStatus.UNKNOWN


def evidence_status(status: Any, *, reason: Any = "") -> str:
    """Return the canonical uppercase status as a plain string."""

    return normalize_evidence_status(status, reason=reason).value


def is_real_hard_pass(
    record: Any,
    *,
    capability: str | None = None,
    require_schema: bool = True,
) -> bool:
    """Whether a record is capability-matched, real hard PASS evidence.

    LLM opinions, unsupported checks, malformed payloads and inactive repair
    transactions are never promoted to hard evidence.
    """

    if normalize_evidence_status(
        getattr(record, "status", ""),
        reason=getattr(record, "description", ""),
    ) is not EvidenceStatus.PASS:
        return False
    if str(getattr(record, "strength", "")).casefold() != "hard":
        return False
    if str(getattr(record, "transaction_status", "active")) != "active":
        return False
    if str(getattr(record, "evidence_type", "")).startswith("llm:"):
        return False
    if capability and str(getattr(record, "capability", "")) != str(capability):
        return False
    invocation = getattr(record, "invocation", {})
    if require_schema and (
        not isinstance(invocation, Mapping)
        or invocation.get("schema_valid") is not True
    ):
        return False
    return True


@dataclass(frozen=True)
class VerificationState:
    """Explicit E6 state vector for one candidate version."""

    schema_valid: bool
    answer_shape_valid: bool
    not_disproved: bool
    semantically_supported: bool
    hard_verified: bool
    audited: bool
    answer_consistent: bool = True
    assurance_level: str = "candidate_valid"
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        values = (
            self.schema_valid,
            self.answer_shape_valid,
            self.not_disproved,
            self.semantically_supported,
            self.hard_verified,
            self.audited,
            self.answer_consistent,
        )
        if any(type(value) is not bool for value in values):
            raise TypeError("VerificationState flags must be booleans")
        # Positive verification is strictly stronger than a negative check.
        # It may coexist with not_disproved, but can never be inferred from it.
        if self.hard_verified and not self.not_disproved:
            raise ValueError("hard_verified requires not_disproved")
        if self.hard_verified and not self.semantically_supported:
            raise ValueError("hard_verified requires semantic support")
        if self.audited and not self.answer_consistent:
            raise ValueError("audited candidate must be answer-consistent")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        return payload


@dataclass(frozen=True)
class CompletionAssessment:
    status: str
    allowed: bool
    best_available: bool
    assurance: str
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        return payload


@dataclass(frozen=True)
class CompletionPolicy:
    """Risk-aware deterministic completion policy."""

    response_mode: str
    risk_level: str
    require_answer_shape: bool = True
    require_no_fatal_hard_fail: bool = True
    require_independent_or_support: bool = False
    require_critical_claim_coverage: bool = False
    require_terminal_consistency: bool = False
    require_zero_critical_obligations: bool = False
    prefer_hard_verified: bool = False
    allow_best_available: bool = False

    @classmethod
    def for_context(
        cls,
        response_mode: str,
        risk_level: str,
    ) -> "CompletionPolicy":
        mode = str(response_mode or "answer_only").casefold()
        risk = str(risk_level or "medium").casefold()
        if mode == "answer_only" and risk == "low":
            return cls(
                mode,
                risk,
                require_independent_or_support=True,
            )
        if mode == "proof_full" and risk == "high":
            return cls(
                mode,
                risk,
                require_critical_claim_coverage=True,
                require_terminal_consistency=True,
                require_zero_critical_obligations=True,
                prefer_hard_verified=True,
                allow_best_available=True,
            )
        if mode in {"worked_solution", "proof", "derivation"}:
            return cls(
                mode,
                risk,
                require_critical_claim_coverage=True,
                require_terminal_consistency=True,
                require_zero_critical_obligations=True,
                allow_best_available=risk != "high",
            )
        # Medium answer-only is retained as a compatibility profile.  The
        # runtime still supplies risk explicitly for competition decisions.
        return cls(mode, risk)

    def evaluate(
        self,
        state: VerificationState | Any,
        *,
        independent_agreement: bool = False,
        independent_corroboration: bool | None = None,
        tool_or_verifier_support: bool = False,
        tool_support: bool | None = None,
        verifier_support: bool | None = None,
        critical_claim_coverage: bool | None = None,
        terminal_consistent: bool | None = None,
        terminal_conclusion_consistent: bool | None = None,
        unresolved_critical_obligations: int = 0,
        fatal_hard_fail: bool = False,
    ) -> CompletionAssessment:
        if independent_corroboration is not None:
            independent_agreement = bool(independent_corroboration)
        if tool_support is not None or verifier_support is not None:
            tool_or_verifier_support = bool(tool_support or verifier_support)
        if terminal_conclusion_consistent is not None:
            terminal_consistent = bool(terminal_conclusion_consistent)
        reasons: list[str] = []
        shape = bool(
            getattr(state, "answer_shape_valid", False)
            if self.require_answer_shape
            else True
        )
        if self.require_answer_shape and not shape:
            reasons.append("answer_shape_invalid")
        if self.require_no_fatal_hard_fail and fatal_hard_fail:
            reasons.append("fatal_hard_failure")
        if self.require_independent_or_support and not (
            independent_agreement or tool_or_verifier_support
        ):
            reasons.append("independent_agreement_or_support_missing")
        coverage = (
            bool(critical_claim_coverage)
            if critical_claim_coverage is not None
            else bool(getattr(state, "semantically_supported", False))
        )
        if self.require_critical_claim_coverage and not coverage:
            reasons.append("critical_claim_coverage_incomplete")
        consistency = (
            bool(terminal_consistent)
            if terminal_consistent is not None
            else bool(getattr(state, "answer_consistent", False))
        )
        if self.require_terminal_consistency and not consistency:
            reasons.append("terminal_conclusion_inconsistent")
        if self.require_zero_critical_obligations and unresolved_critical_obligations:
            reasons.append("critical_obligation_unresolved")
        assurance = str(getattr(state, "assurance_level", "candidate_valid"))
        hard = bool(getattr(state, "hard_verified", False))
        audited = bool(getattr(state, "audited", False))
        if self.prefer_hard_verified and not (hard or audited):
            reasons.append("hard_verification_or_audit_preferred")
        base_ok = not reasons
        if base_ok:
            return CompletionAssessment("complete", True, False, assurance)
        if self.allow_best_available and shape and not fatal_hard_fail:
            return CompletionAssessment(
                "best_available",
                True,
                True,
                assurance,
                tuple(dict.fromkeys(reasons)),
            )
        return CompletionAssessment(
            "incomplete",
            False,
            False,
            assurance,
            tuple(dict.fromkeys(reasons)),
        )

    assess = evaluate


@dataclass(frozen=True)
class AnswerConsistency:
    """Public consistency result across answer-producing boundaries."""

    candidate_id: str
    normalized_answer: str
    consistent: bool
    fully_checked: bool
    checked_edges: tuple[str, ...] = ()
    mismatches: tuple[str, ...] = ()
    unknown_edges: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("checked_edges", "mismatches", "unknown_edges"):
            payload[key] = list(payload[key])
        return payload

    @property
    def is_consistent(self) -> bool:
        return self.consistent


def _extract_comparable_answer(value: Any, answer_type: str) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        # Lazy imports avoid loading the evaluation/output package while the
        # verification package itself is being initialized.
        from mathforge.output.deterministic_formatter import exact_final_answer

        text = exact_final_answer(value, answer_type)
        # Terminal claims and proof conclusions often use ``x = answer`` or
        # ``... is answer``.  Only strip a prose prefix when a clear delimiter
        # exists; otherwise leave the edge unknown instead of guessing.
        has_delimiter = False
        if "=" in text and not text.lstrip().startswith("="):
            has_delimiter = True
            text = text.rsplit("=", 1)[-1].strip()
        elif re.search(r"\b(?:is|equals|为)\s+", text, re.I):
            has_delimiter = True
            text = re.split(r"\b(?:is|equals|为)\s+", text, maxsplit=1, flags=re.I)[-1]
        elif not answer_shape_valid(text, answer_type):
            return ""
        elif str(answer_type).casefold() not in {"text", "explanation", "derivation"} and len(text.split()) > 3:
            # A prose Claim without an explicit conclusion delimiter is not a
            # reliable answer edge.  Treat it as unknown instead of declaring
            # a mismatch against the candidate's canonical answer.
            return ""
        return canonical_answer(text, answer_type)
    if isinstance(value, Mapping):
        for key in (
            "canonical_answer",
            "final_answer",
            "answer",
            "value",
            "result",
            "expected_answer",
        ):
            if key in value and not isinstance(value[key], (dict, list, tuple)):
                answer = _extract_comparable_answer(value[key], answer_type)
                if answer:
                    return answer
    return ""


def assess_answer_consistency(
    candidate: Any,
    *,
    terminal_claim: Any | None = None,
    tool_results: Iterable[Any] = (),
    proof_conclusion: Any | None = None,
    formatter_output: str = "",
    scorer_normalized_answer: str = "",
    scorer_output: str = "",
) -> AnswerConsistency:
    """Compare every available answer boundary deterministically."""

    from mathforge.evaluation.scoring import extract_final_answer

    answer_type = candidate.answer_type
    expected = canonical_answer(candidate.final_answer, answer_type)
    checked: list[str] = []
    mismatches: list[str] = []
    unknown: list[str] = []

    if not expected or not answer_shape_valid(candidate.final_answer, answer_type):
        mismatches.append("candidate.final_answer")

    terminal_value = terminal_claim
    if terminal_value is None and candidate.claims:
        terminal_value = candidate.claims[-1].statement
    if terminal_value is not None:
        actual = _extract_comparable_answer(terminal_value, answer_type)
        if actual:
            checked.append("terminal_claim")
            if actual != expected:
                mismatches.append("terminal_claim")
        else:
            unknown.append("terminal_claim")

    if proof_conclusion is not None:
        actual = _extract_comparable_answer(proof_conclusion, answer_type)
        if actual:
            checked.append("proof_conclusion")
            if actual != expected:
                mismatches.append("proof_conclusion")
        else:
            unknown.append("proof_conclusion")

    for index, result in enumerate(tool_results):
        status = normalize_evidence_status(
            getattr(result, "status", ""),
            reason=getattr(result, "summary", ""),
        )
        payload = getattr(result, "payload", None)
        if status is not EvidenceStatus.PASS:
            # A hard failure is evidence against the candidate, while an
            # unknown/unsupported result is simply not a consistency edge.
            if status is EvidenceStatus.FAIL:
                mismatches.append(f"tool_result:{index}")
            continue
        actual = _extract_comparable_answer(payload, answer_type)
        if not actual:
            actual = _extract_comparable_answer(result, answer_type)
        if actual:
            checked.append(f"tool_result:{index}")
            if actual != expected:
                mismatches.append(f"tool_result:{index}")

    if formatter_output:
        actual = _extract_comparable_answer(
            extract_final_answer(formatter_output),
            answer_type,
        )
        if actual:
            checked.append("formatter")
            if actual != expected:
                mismatches.append("formatter")
        else:
            unknown.append("formatter")

    if scorer_output:
        actual = _extract_comparable_answer(
            extract_final_answer(scorer_output),
            answer_type,
        )
        if actual:
            checked.append("scorer")
            if actual != expected:
                mismatches.append("scorer")
        else:
            unknown.append("scorer")
    if scorer_normalized_answer:
        actual = canonical_answer(scorer_normalized_answer, answer_type)
        checked.append("scorer_normalization")
        if actual != expected:
            mismatches.append("scorer_normalization")

    consistent = not mismatches and bool(expected)
    return AnswerConsistency(
        candidate_id=candidate.candidate_id,
        normalized_answer=expected,
        consistent=consistent,
        fully_checked=bool(checked) and not unknown and not mismatches,
        checked_edges=tuple(dict.fromkeys(checked)),
        mismatches=tuple(dict.fromkeys(mismatches)),
        unknown_edges=tuple(dict.fromkeys(unknown)),
    )


@dataclass(frozen=True)
class CognitiveProvenance:
    method_family: str = ""
    shared_context_hash: str = ""
    private_context_hash: str = ""
    skill_set_hash: str = ""
    lemma_ids: tuple[str, ...] = ()
    proof_backbone_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["lemma_ids"] = list(self.lemma_ids)
        return payload


@dataclass(frozen=True)
class AtomicRepairClosure:
    """Admission decision for repair + reverify + audit as one transaction."""

    admitted: bool
    repair_p95_seconds: float
    reverify_p95_seconds: float
    final_audit_p95_seconds: float
    finalize_reserve_seconds: float
    required_seconds: float
    remaining_seconds: float
    reason: str
    candidate_retained: bool = True
    best_available: bool = False

    @classmethod
    def admit(
        cls,
        *,
        repair_p95_seconds: float,
        reverify_p95_seconds: float,
        final_audit_p95_seconds: float,
        finalize_reserve_seconds: float,
        remaining_seconds: float,
        remaining_calls: int = 3,
        required_calls: int = 3,
        model_start_margin_seconds: float = 0.0,
    ) -> "AtomicRepairClosure":
        values = [
            max(0.0, float(item))
            for item in (
                repair_p95_seconds,
                reverify_p95_seconds,
                final_audit_p95_seconds,
                finalize_reserve_seconds,
                remaining_seconds,
                model_start_margin_seconds,
            )
        ]
        repair, reverify, audit, reserve, remaining, margin = values
        required = repair + reverify + audit + reserve + margin
        if int(remaining_calls) < int(required_calls):
            reason = "insufficient_call_capacity"
        elif remaining < required:
            reason = "insufficient_time_capacity"
        else:
            reason = "admitted"
        admitted = reason == "admitted"
        return cls(
            admitted,
            repair,
            reverify,
            audit,
            reserve,
            round(required, 6),
            remaining,
            reason,
            candidate_retained=True,
            best_available=not admitted,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def evaluate(cls, **kwargs: Any) -> "AtomicRepairClosure":
        return cls.admit(**kwargs)


@dataclass(frozen=True)
class FinalAuditCoverage:
    candidate_id: str
    candidate_version: int
    active_version: int
    required_artifact_ids: tuple[str, ...] = ()
    reviewed_artifact_ids: tuple[str, ...] = ()
    required_finding_ids: tuple[str, ...] = ()
    reviewed_finding_ids: tuple[str, ...] = ()
    required_obligation_ids: tuple[str, ...] = ()
    reviewed_obligation_ids: tuple[str, ...] = ()
    open_finding_ids: tuple[str, ...] = ()
    open_obligation_ids: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return (
            self.candidate_version == self.active_version
            and set(self.required_artifact_ids) <= set(self.reviewed_artifact_ids)
            and set(self.required_finding_ids) <= set(self.reviewed_finding_ids)
            and set(self.required_obligation_ids) <= set(self.reviewed_obligation_ids)
            and not self.open_finding_ids
            and not self.open_obligation_ids
        )

    @classmethod
    def from_audit(
        cls,
        audit: Any,
        *,
        active_candidate_version: int,
    ) -> "FinalAuditCoverage":
        return final_audit_coverage(
            audit,
            active_candidate_version=active_candidate_version,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "required_artifact_ids",
            "reviewed_artifact_ids",
            "required_finding_ids",
            "reviewed_finding_ids",
            "required_obligation_ids",
            "reviewed_obligation_ids",
            "open_finding_ids",
            "open_obligation_ids",
        ):
            payload[key] = list(payload[key])
        payload["complete"] = self.complete
        return payload


def final_audit_coverage(
    audit: Any,
    *,
    active_candidate_version: int,
) -> FinalAuditCoverage:
    """Build the exact E6 final-audit coverage view from an AuditRecord."""

    return FinalAuditCoverage(
        candidate_id=str(getattr(audit, "candidate_id", "")),
        candidate_version=int(getattr(audit, "candidate_version", -1)),
        active_version=int(active_candidate_version),
        required_artifact_ids=tuple(getattr(audit, "required_artifact_ids", ())),
        reviewed_artifact_ids=tuple(getattr(audit, "reviewed_artifact_ids", ())),
        required_finding_ids=tuple(getattr(audit, "required_finding_ids", ())),
        reviewed_finding_ids=tuple(getattr(audit, "reviewed_finding_ids", ())),
        required_obligation_ids=tuple(getattr(audit, "required_obligation_ids", ())),
        reviewed_obligation_ids=tuple(getattr(audit, "reviewed_obligation_ids", ())),
        open_finding_ids=tuple(getattr(audit, "open_finding_ids", ())),
        open_obligation_ids=tuple(getattr(audit, "open_obligation_ids", ())),
    )


# Descriptive aliases used by phase reports and integration callers.
VerificationStateVector = VerificationState
RiskAwareCompletionPolicy = CompletionPolicy
AnswerConsistencyResult = AnswerConsistency
RepairClosureAdmission = AtomicRepairClosure
ToolEvidenceStatus = EvidenceStatus


__all__ = [
    "AnswerConsistency",
    "AnswerConsistencyResult",
    "AtomicRepairClosure",
    "CognitiveProvenance",
    "CompletionAssessment",
    "CompletionPolicy",
    "EvidenceStatus",
    "ToolEvidenceStatus",
    "FinalAuditCoverage",
    "REPAIR_ACTIONS",
    "RepairErrorCategory",
    "RepairClosureAdmission",
    "RiskAwareCompletionPolicy",
    "VerificationState",
    "VerificationStateVector",
    "assess_answer_consistency",
    "classify_repair_error",
    "evidence_status",
    "final_audit_coverage",
    "is_real_hard_pass",
    "normalize_repair_category",
    "normalize_evidence_status",
]
