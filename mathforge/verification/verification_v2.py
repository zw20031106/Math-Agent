"""Deterministic Verification V2 closure and assurance semantics.

The legacy proof status strings remain available for wire compatibility, but
they are not evidence claims.  This module is the single source of truth for
the stronger statement that a candidate is supported: a host-selected
conclusion, its dependency closure, real obligation mappings, and compatible
evidence must all agree.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from mathforge.harness.schemas import CandidateSolution, EvidenceRecord, ProofObligation
from mathforge.verification.capabilities import capability_satisfies_obligation
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
    # Versioned terminal metadata shared by completion, arbitration and trace.
    completion_status: str = "incomplete"
    candidate_version: int = 1
    audit_id: str = ""
    audit_status: str = ""
    repaired: bool = False
    repair_transaction_status: str = ""
    active_evidence_ids: tuple[str, ...] = ()
    semantic_step_count: int = 0
    mapped_semantic_step_count: int = 0
    derivation_quality: str = "unknown"
    required_coverage: float = 0.0

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
            "active_evidence_ids",
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


def _matching_audit(candidate: CandidateSolution, audits: Iterable[Any]) -> Any | None:
    for audit in reversed(tuple(audits)):
        if (
            str(getattr(audit, "candidate_id", "")) == candidate.candidate_id
            and int(getattr(audit, "candidate_version", -1)) == int(candidate.version)
            and str(getattr(audit, "status", "")) in {"complete_audited", "complete_hard"}
            and not getattr(audit, "open_finding_ids", ())
            and not getattr(audit, "open_obligation_ids", ())
            and bool(getattr(audit, "coverage_complete", True))
        ):
            return audit
    return None


def _audit_matches(candidate: CandidateSolution, audits: Iterable[Any]) -> bool:
    return _matching_audit(candidate, audits) is not None


def _semantic_step_quality(
    candidate: CandidateSolution,
    *,
    response_mode: str,
) -> tuple[int, int, str]:
    """Measure public derivation coverage without counting answer echoes.

    The model supplies public step text and the Host owns Claim/MethodStep
    identifiers.  A step is mapped only when its referenced Claim exists (or
    when the Host can prove a one-to-one statement match), so a parser-created
    ``Final answer: ...`` line cannot masquerade as reasoning.
    """

    steps = [
        str(item).strip()
        for item in candidate.public_solution_steps
        if str(item).strip()
    ]
    claim_ids = {claim.claim_id for claim in candidate.claims}
    mapped = 0
    for index, step in enumerate(steps):
        explicit = (
            candidate.method_steps[index].claim_ids
            if index < len(candidate.method_steps)
            else []
        )
        if explicit and set(explicit) <= claim_ids:
            mapped += 1
            continue
        if (
            index < len(candidate.claims)
            and candidate.claims[index].statement.strip() == step
        ):
            mapped += 1

    answer = " ".join(str(candidate.final_answer).split()).casefold()
    answer_only_prefix = re.compile(
        r"^(?:final\s+answer|answer|答案)\s*[:：]?\s*", re.IGNORECASE
    )
    answer_only = bool(steps) and all(
        answer_only_prefix.sub("", step).strip().casefold() == answer
        for step in steps
    )
    # Legacy fixtures may contain public steps and Claims but no explicit
    # MethodStep metadata.  The Host's positional projection is the only safe
    # compatibility mapping in that case; a claimless answer remains
    # answer-only and cannot pass this branch.
    if not candidate.method_steps and len(steps) >= 2 and candidate.claims and not answer_only:
        mapped = len(steps)
    if not steps or answer_only:
        quality = "answer_only"
    elif mapped == len(steps) and candidate.claims:
        quality = "complete"
    elif mapped:
        quality = "partial"
    else:
        quality = "answer_only"
    if response_mode == "proof_full" and (len(steps) < 2 or quality != "complete"):
        quality = "partial" if steps else "answer_only"
    return len(steps), mapped, quality


def assess_verification(
    candidate: CandidateSolution,
    evidence: Iterable[EvidenceRecord],
    obligations: Iterable[ProofObligation],
    *,
    audits: Iterable[Any] = (),
    independently_corroborated: bool = False,
    response_mode: str = "answer_only",
    repaired: bool = False,
    repair_lineage: Iterable[dict[str, Any]] = (),
) -> VerificationClosure:
    """Assess the candidate using only terminal-closure evidence."""

    obligations_list = list(obligations)
    own_evidence = [
        record
        for record in evidence
        if record.candidate_id == candidate.candidate_id
        and record.transaction_status == "active"
    ]
    semantic_step_count, mapped_semantic_step_count, derivation_quality = (
        _semantic_step_quality(candidate, response_mode=response_mode)
    )
    conclusion_id = resolve_conclusion_claim_id(candidate)
    closure = critical_dependency_closure(candidate, conclusion_id)
    closure_set = set(closure)
    claim_by_id = {claim.claim_id: claim for claim in candidate.claims}

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
    repair_status = ""
    for lineage in reversed(tuple(repair_lineage)):
        if not isinstance(lineage, dict):
            continue
        if str(lineage.get("proposed_candidate_id", "")) == candidate.candidate_id:
            repair_status = str(lineage.get("transaction_status", ""))
            break
    reasons: list[str] = []
    if not conclusion_id:
        reasons.append("conclusion_claim_missing_or_ambiguous")
    if not closure:
        reasons.append("critical_dependency_closure_empty")
    if unmapped:
        reasons.append("unmapped_required_obligation")
    if fatal_closure:
        reasons.append("critical_closure_hard_failure")
    if repair_status in {"rolled_back", "rejected"}:
        reasons.append("repair_transaction_inactive")
    if response_mode == "proof_full" and derivation_quality != "complete":
        reasons.append("proof_full_derivation_incomplete")
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

    matching_audit = _matching_audit(candidate, audits)
    audited = bool(
        answer_contract_valid
        and closure
        and not unmapped
        and matching_audit is not None
    )
    if audited:
        assurance = "audited"
    if _formal_support(own_evidence, closure_set, required):
        assurance = "formally_verified"

    proof_shape_terminal = not (
        response_mode == "proof_full" and derivation_quality != "complete"
    )
    terminal = bool(
        conclusion_id
        and closure
        and not unmapped
        and repair_status not in {"rolled_back", "rejected"}
        and proof_shape_terminal
        and (
            tool_supported
            or audited
            or assurance == "formally_verified"
        )
    )
    if fatal_closure or repair_status in {"rolled_back", "rejected"}:
        completion_status = "failed"
    elif response_mode == "proof_full" and derivation_quality != "complete":
        completion_status = "incomplete"
    elif audited:
        completion_status = "complete_audited"
    elif tool_supported or assurance == "formally_verified":
        completion_status = "complete_hard"
    elif not required and answer_contract_valid:
        # Compatibility status for answer-only candidates.  The assurance and
        # terminal flags remain authoritative about mathematical closure.
        completion_status = "complete_hard"
    else:
        completion_status = "incomplete"

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
        completion_status=completion_status,
        candidate_version=int(candidate.version),
        audit_id=(
            str(getattr(matching_audit, "audit_id", ""))
            if matching_audit is not None
            else ""
        ),
        audit_status=(
            str(getattr(matching_audit, "status", ""))
            if matching_audit is not None
            else ""
        ),
        repaired=bool(repaired),
        repair_transaction_status=repair_status,
        active_evidence_ids=tuple(
            sorted(record.evidence_id for record in own_evidence)
        ),
        semantic_step_count=semantic_step_count,
        mapped_semantic_step_count=mapped_semantic_step_count,
        derivation_quality=derivation_quality,
        required_coverage=(
            len(set(supported)) / len(required_ids)
            if required_ids
            else 1.0
        ),
    )


__all__ = [
    "ASSURANCE_LEVELS",
    "VerificationClosure",
    "assess_verification",
    "critical_dependency_closure",
    "resolve_conclusion_claim_id",
    "_semantic_step_quality",
]
