"""Deterministic Verification V2 closure and assurance semantics.

The legacy proof status strings remain available for wire compatibility, but
they are not evidence claims.  This module is the single source of truth for
the stronger statement that a candidate is supported: a host-selected
conclusion, its dependency closure, real obligation mappings, and compatible
evidence must all agree.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from mathforge.harness.schemas import CandidateSolution, EvidenceRecord, ProofObligation
from mathforge.verification.capabilities import (
    capability_satisfies_obligation,
    derive_claim_kind,
)
from mathforge.verification.evidence import (
    is_fatal_hard_failure,
    is_semantic_hard_pass,
)


ASSURANCE_LEVELS = (
    "candidate_valid",
    "answer_contract_valid",
    "not_disproved",
    "independently_corroborated",
    "tool_supported",
    "audited",
    "formally_verified",
)

_ASSURANCE_RANK = {name: index for index, name in enumerate(ASSURANCE_LEVELS)}
_FORMAL_CAPABILITY = "formal.proof"


@dataclass(frozen=True)
class VerificationClosure:
    """The host-authored terminal verification view for one Candidate."""

    candidate_id: str
    conclusion_claim_id: str
    critical_claim_ids: tuple[str, ...]
    required_obligation_ids: tuple[str, ...]
    mapped_required_obligation_ids: tuple[str, ...]
    unmapped_required_obligation_ids: tuple[str, ...]
    supported_obligation_ids: tuple[str, ...]
    supporting_evidence_ids: tuple[str, ...]
    assurance_level: str
    terminal_closure: bool
    reasons: tuple[str, ...] = ()

    @property
    def hard_verified(self) -> bool:
        """Compatibility predicate for consumers that need a boolean.

        It deliberately excludes ``complete_hard`` and model-only review.
        """

        return self.terminal_closure and self.assurance_level in {
            "tool_supported",
            "audited",
            "formally_verified",
        }

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for name in (
            "critical_claim_ids",
            "required_obligation_ids",
            "mapped_required_obligation_ids",
            "unmapped_required_obligation_ids",
            "supported_obligation_ids",
            "supporting_evidence_ids",
            "reasons",
        ):
            payload[name] = list(payload[name])
        payload["hard_verified"] = self.hard_verified
        return payload


def resolve_conclusion_claim_id(candidate: CandidateSolution) -> str:
    """Resolve the conclusion deterministically at the Host boundary.

    An explicit conclusion MethodStep wins.  For older Candidates that did
    not emit MethodStep metadata, a single critical claim, a single claim, or
    the final claim is used as a deterministic compatibility projection.  This
    projection never maps a missing obligation to an unrelated claim.
    """

    claim_ids = {claim.claim_id for claim in candidate.claims}
    explicit = list(
        dict.fromkeys(
            claim_id
            for step in candidate.method_steps
            if step.kind == "conclusion"
            for claim_id in step.claim_ids
            if claim_id in claim_ids
        )
    )
    if len(explicit) == 1:
        return explicit[0]
    if len(explicit) > 1:
        return ""
    critical = [
        claim.claim_id
        for claim in candidate.claims
        if claim.importance in {"critical", "required"}
    ]
    if len(critical) == 1:
        return critical[0]
    if len(candidate.claims) == 1:
        return candidate.claims[0].claim_id
    return candidate.claims[-1].claim_id if candidate.claims else ""


def critical_dependency_closure(
    candidate: CandidateSolution,
    conclusion_claim_id: str | None = None,
) -> tuple[str, ...]:
    """Return the conclusion and all transitive claim dependencies."""

    by_id = {claim.claim_id: claim for claim in candidate.claims}
    conclusion = conclusion_claim_id or resolve_conclusion_claim_id(candidate)
    if not conclusion or conclusion not in by_id:
        return ()
    ordered: list[str] = []
    seen: set[str] = set()

    def visit(claim_id: str) -> None:
        if claim_id in seen or claim_id not in by_id:
            return
        seen.add(claim_id)
        ordered.append(claim_id)
        for dependency in by_id[claim_id].depends_on:
            visit(dependency)

    visit(conclusion)
    return tuple(ordered)


def _record_obligation_ids(record: EvidenceRecord) -> set[str]:
    value = record.payload.get("obligation_ids", [])
    return {str(item) for item in value} if isinstance(value, (list, tuple, set)) else set()


def _compatible_hard_obligation_evidence(
    record: EvidenceRecord,
    obligation: ProofObligation,
    closure_claim_ids: set[str],
) -> bool:
    if record.claim_id not in closure_claim_ids:
        return False
    if record.status != "pass" or record.strength != "hard":
        return False
    if record.transaction_status != "active":
        return False
    if obligation.obligation_id not in _record_obligation_ids(record):
        return False
    # A VerifierSkeptic opinion is always soft, even if a malformed record
    # claims otherwise.  A deterministic formal executor is explicit.
    if str(record.evidence_type).startswith("llm:"):
        return False
    if str(record.capability) == _FORMAL_CAPABILITY:
        return bool(record.invocation.get("formal_engine") is True)
    return capability_satisfies_obligation(record.capability, obligation.kind)


def _formal_support(
    own_evidence: list[EvidenceRecord],
    closure_claim_ids: set[str],
    required: list[ProofObligation],
) -> bool:
    records = [
        record
        for record in own_evidence
        if (
            record.status == "pass"
            and record.strength == "hard"
            and record.transaction_status == "active"
            and record.evidence_type and not str(record.evidence_type).startswith("llm:")
            and record.capability == _FORMAL_CAPABILITY
            and record.invocation.get("formal_engine") is True
            and record.claim_id in closure_claim_ids
        )
    ]
    if not records:
        return False
    if not required:
        return True
    evidence_obligations = set().union(
        *(_record_obligation_ids(record) for record in records)
    )
    return all(item.obligation_id in evidence_obligations for item in required)


def _audit_matches(candidate: CandidateSolution, audits: Iterable[Any]) -> bool:
    for audit in reversed(tuple(audits)):
        if (
            str(getattr(audit, "candidate_id", "")) == candidate.candidate_id
            and int(getattr(audit, "candidate_version", -1)) == int(candidate.version)
            and str(getattr(audit, "status", "")) in {"complete_audited", "complete_hard"}
            and not getattr(audit, "open_finding_ids", ())
            and not getattr(audit, "open_obligation_ids", ())
            and bool(getattr(audit, "coverage_complete", True))
        ):
            return True
    return False


def assess_verification(
    candidate: CandidateSolution,
    evidence: Iterable[EvidenceRecord],
    obligations: Iterable[ProofObligation],
    *,
    audits: Iterable[Any] = (),
    independently_corroborated: bool = False,
) -> VerificationClosure:
    """Assess the candidate using only terminal-closure evidence."""

    obligations_list = list(obligations)
    own_evidence = [
        record
        for record in evidence
        if record.candidate_id == candidate.candidate_id
        and record.transaction_status == "active"
    ]
    conclusion_id = resolve_conclusion_claim_id(candidate)
    closure = critical_dependency_closure(candidate, conclusion_id)
    closure_set = set(closure)
    claim_by_id = {claim.claim_id: claim for claim in candidate.claims}
    for claim in candidate.claims:
        if claim.claim_kind == "unknown":
            claim.claim_kind = derive_claim_kind(claim.check_type)

    required = [item for item in obligations_list if item.required]
    required_ids = tuple(item.obligation_id for item in required)
    mapped: list[str] = []
    unmapped: list[str] = []
    for item in required:
        sources = [claim_id for claim_id in item.source_claim_ids if claim_id in claim_by_id]
        if sources:
            mapped.append(item.obligation_id)
        else:
            unmapped.append(item.obligation_id)

    supported: list[str] = []
    support_evidence: list[str] = []
    for item in required:
        records = [
            record
            for record in own_evidence
            if _compatible_hard_obligation_evidence(record, item, closure_set)
        ]
        if records and item.status != "failed":
            supported.append(item.obligation_id)
            support_evidence.extend(record.evidence_id for record in records)

    fatal_closure = {
        record.claim_id
        for record in own_evidence
        if record.claim_id in closure_set and is_fatal_hard_failure(record)
    }
    candidate_valid = bool(candidate.candidate_id.strip())
    answer_contract_valid = candidate_valid and bool(
        candidate.final_answer.strip() and candidate.answer_type.strip()
    )
    reasons: list[str] = []
    if not conclusion_id:
        reasons.append("conclusion_claim_missing_or_ambiguous")
    if not closure:
        reasons.append("critical_dependency_closure_empty")
    if unmapped:
        reasons.append("unmapped_required_obligation")
    if fatal_closure:
        reasons.append("critical_closure_hard_failure")
    if any(
        claim_by_id[claim_id].status == "rejected"
        for claim_id in closure_set
        if claim_id in claim_by_id
    ):
        reasons.append("critical_claim_rejected")

    assurance = "candidate_valid" if candidate_valid else "candidate_valid"
    if answer_contract_valid:
        assurance = "answer_contract_valid"
    if answer_contract_valid and closure and not fatal_closure and not unmapped:
        assurance = "not_disproved"
    if independently_corroborated and _ASSURANCE_RANK[assurance] >= _ASSURANCE_RANK["not_disproved"]:
        assurance = "independently_corroborated"

    required_supported = bool(required) and set(supported) == set(required_ids)
    conclusion_tool_supported = any(
        record.claim_id == conclusion_id
        and is_semantic_hard_pass(record)
        and record.claim_id in closure_set
        for record in own_evidence
    )
    tool_supported = bool(
        answer_contract_valid
        and closure
        and not fatal_closure
        and not unmapped
        and (
            required_supported
            if required
            else conclusion_tool_supported
        )
    )
    if tool_supported:
        assurance = "tool_supported"

    audited = bool(
        answer_contract_valid
        and closure
        and not unmapped
        and _audit_matches(candidate, audits)
    )
    if audited:
        assurance = "audited"
    if _formal_support(own_evidence, closure_set, required):
        assurance = "formally_verified"

    terminal = bool(
        conclusion_id
        and closure
        and not unmapped
        and (
            tool_supported
            or audited
            or assurance == "formally_verified"
        )
    )
    return VerificationClosure(
        candidate_id=candidate.candidate_id,
        conclusion_claim_id=conclusion_id,
        critical_claim_ids=closure,
        required_obligation_ids=required_ids,
        mapped_required_obligation_ids=tuple(mapped),
        unmapped_required_obligation_ids=tuple(unmapped),
        supported_obligation_ids=tuple(sorted(set(supported))),
        supporting_evidence_ids=tuple(sorted(set(support_evidence))),
        assurance_level=assurance,
        terminal_closure=terminal,
        reasons=tuple(dict.fromkeys(reasons)),
    )


__all__ = [
    "ASSURANCE_LEVELS",
    "VerificationClosure",
    "assess_verification",
    "critical_dependency_closure",
    "resolve_conclusion_claim_id",
]
