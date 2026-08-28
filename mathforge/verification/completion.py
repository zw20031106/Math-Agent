from __future__ import annotations

from dataclasses import asdict, dataclass, field

from mathforge.harness.schemas import CandidateSolution, EvidenceRecord, ProofObligation
from mathforge.verification.capabilities import (
    VerificationCapability,
    capability_satisfies_obligation,
)
from mathforge.verification.evidence import is_fatal_hard_failure
from mathforge.verification.e6 import CompletionAssessment, CompletionPolicy
from mathforge.verification.verification_v2 import assess_verification


@dataclass(frozen=True)
class CompletionDecision:
    candidate_id: str
    status: str
    unresolved_obligation_ids: list[str]
    failed_obligation_ids: list[str]
    failed_claim_ids: list[str]
    hard_satisfied_obligation_ids: list[str]
    model_reviewed_obligation_ids: list[str]
    evidence_tier: str
    assurance_level: str = "candidate_valid"
    conclusion_claim_id: str = ""
    critical_claim_ids: list[str] = field(default_factory=list)
    unmapped_required_obligation_ids: list[str] = field(default_factory=list)
    supporting_evidence_ids: list[str] = field(default_factory=list)
    terminal_closure: bool = False
    assurance_reasons: list[str] = field(default_factory=list)
    verification_closure: object | None = None
    policy_status: str = "legacy"
    policy_allowed: bool = True
    best_available: bool = False
    policy_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def hard_verified(self) -> bool:
        """Whether the stronger V2 terminal closure is actually complete."""

        return self.terminal_closure and self.assurance_level in {
            "tool_supported",
            "audited",
            "formally_verified",
        }


class ProofCompletionGate:
    """Require every required proof obligation to have mapped evidence."""

    def evaluate(
        self,
        candidate: CandidateSolution,
        evidence: list[EvidenceRecord],
        obligations: list[ProofObligation],
        *,
        response_mode: str = "answer_only",
        audits=(),
        repaired: bool = False,
        repair_lineage=(),
        risk_level: str | None = None,
        completion_policy: CompletionPolicy | None = None,
        independent_agreement: bool = False,
        tool_or_verifier_support: bool | None = None,
        terminal_consistent: bool | None = None,
        critical_claim_coverage: bool | None = None,
    ) -> CompletionDecision:
        own_evidence = [
            record
            for record in evidence
            if record.candidate_id == candidate.candidate_id
            and record.transaction_status == "active"
        ]
        failed_claims = sorted(
            {
                record.claim_id
                for record in own_evidence
                if record.claim_id is not None
                and is_fatal_hard_failure(record)
            }
        )
        failed_obligations = sorted(
            obligation.obligation_id
            for obligation in obligations
            if obligation.required and obligation.status == "failed"
        )
        if failed_claims or failed_obligations:
            candidate.unresolved_obligations = sorted(
                {
                    obligation.obligation_id
                    for obligation in obligations
                    if obligation.required and obligation.status != "satisfied"
                }
            )
            closure = assess_verification(
                candidate,
                own_evidence,
                obligations,
                audits=audits,
                response_mode=response_mode,
                repaired=repaired,
                repair_lineage=repair_lineage,
            )
            policy_assessment = self._policy_assessment(
                closure,
                response_mode=response_mode,
                risk_level=risk_level,
                completion_policy=completion_policy,
                independent_agreement=independent_agreement,
                tool_or_verifier_support=tool_or_verifier_support,
                terminal_consistent=terminal_consistent,
                critical_claim_coverage=critical_claim_coverage,
                unresolved_critical=len(failed_obligations),
                fatal_hard_fail=True,
            )
            return _decision(
                candidate,
                "failed",
                list(candidate.unresolved_obligations),
                failed_obligations,
                failed_claims,
                [],
                [],
                "incomplete",
                closure,
                policy_assessment,
            )

        unresolved: list[str] = []
        hard_satisfied: list[str] = []
        model_reviewed: list[str] = []
        for obligation in obligations:
            if not obligation.required:
                continue
            source_claim_ids = {
                claim.claim_id
                for claim in candidate.claims
                if claim.claim_id in set(obligation.source_claim_ids)
            }
            if not source_claim_ids:
                # This is intentionally distinct from a merely unverified
                # Claim.  Completion must not hide a missing obligation edge.
                # Preserve the old status for a hand-built pre-satisfied
                # fixture, while engine-generated obligations retain the V2
                # unmapped status.
                if obligation.status == "satisfied":
                    obligation.status = "unresolved"
                elif obligation.status != "unmapped_required_obligation":
                    obligation.status = "unmapped_required_obligation"
                obligation.satisfaction_evidence_ids = []
                unresolved.append(obligation.obligation_id)
                continue
            hard_evidence = [
                record
                for record in own_evidence
                if record.status == "pass"
                and record.claim_id in source_claim_ids
                and obligation.obligation_id in record.payload.get("obligation_ids", [])
                and capability_satisfies_obligation(
                    record.capability,
                    obligation.kind,
                )
                and record.strength == "hard"
                and not record.evidence_type.startswith("llm:")
            ]
            soft_model_evidence = [
                record
                for record in own_evidence
                if record.status == "pass"
                and record.strength == "soft"
                and record.claim_id in source_claim_ids
                and obligation.obligation_id
                in record.payload.get("obligation_ids", [])
                and record.capability
                == VerificationCapability.PROOF_OBLIGATION_REVIEW.value
            ]
            if hard_evidence:
                obligation.status = "satisfied"
                obligation.satisfaction_evidence_ids = sorted(
                    record.evidence_id for record in hard_evidence
                )
                hard_satisfied.append(obligation.obligation_id)
            elif soft_model_evidence:
                obligation.status = "reviewed"
                obligation.satisfaction_evidence_ids = sorted(
                    record.evidence_id
                    for record in soft_model_evidence
                )
                model_reviewed.append(obligation.obligation_id)
                unresolved.append(obligation.obligation_id)
            else:
                obligation.status = "unresolved"
                obligation.satisfaction_evidence_ids = []
                unresolved.append(obligation.obligation_id)

        candidate.unresolved_obligations = sorted(unresolved)
        required = [
            obligation
            for obligation in obligations
            if obligation.required
        ]
        proof_shape_complete = (
            response_mode != "proof_full"
            or len(
                [
                    item
                    for item in candidate.public_solution_steps
                    if str(item).strip()
                ]
            )
            >= 2
        )
        if not proof_shape_complete:
            status = "incomplete"
            evidence_tier = "incomplete"
        elif not required:
            status = "complete_hard"
            evidence_tier = "not_required"
        elif not unresolved:
            status = "complete_hard"
            evidence_tier = "hard_evidence"
        else:
            status = "incomplete"
            evidence_tier = (
                "model_review"
                if set(unresolved) == set(model_reviewed)
                else "incomplete"
            )
        closure = assess_verification(
            candidate,
            own_evidence,
            obligations,
            audits=audits,
            response_mode=response_mode,
            repaired=repaired,
            repair_lineage=repair_lineage,
        )
        unresolved_critical = sum(
            1
            for item in obligations
            if item.required
            and item.status != "satisfied"
            and (
                str(item.kind).casefold() in {"critical", "terminal", "conclusion"}
                or any(
                    claim.claim_id in set(closure.critical_claim_ids)
                    for claim in candidate.claims
                    if claim.claim_id in set(item.source_claim_ids)
                )
            )
        )
        policy_assessment = self._policy_assessment(
            closure,
            response_mode=response_mode,
            risk_level=risk_level,
            completion_policy=completion_policy,
            independent_agreement=independent_agreement,
            tool_or_verifier_support=tool_or_verifier_support,
            terminal_consistent=terminal_consistent,
            critical_claim_coverage=critical_claim_coverage,
            unresolved_critical=unresolved_critical,
            fatal_hard_fail=False,
        )
        return _decision(
            candidate,
            status,
            sorted(unresolved),
            [],
            [],
            sorted(hard_satisfied),
            sorted(model_reviewed),
            evidence_tier,
            closure,
            policy_assessment,
        )

    @staticmethod
    def _policy_assessment(
        closure,
        *,
        response_mode: str,
        risk_level: str | None,
        completion_policy: CompletionPolicy | None,
        independent_agreement: bool,
        tool_or_verifier_support: bool | None,
        terminal_consistent: bool | None,
        critical_claim_coverage: bool | None,
        unresolved_critical: int,
        fatal_hard_fail: bool,
    ) -> CompletionAssessment | None:
        if completion_policy is None and risk_level is None:
            return None
        policy = completion_policy or CompletionPolicy.for_context(
            response_mode,
            str(risk_level or "medium"),
        )
        return policy.evaluate(
            closure.state,
            independent_agreement=independent_agreement,
            tool_or_verifier_support=(
                closure.semantically_supported
                if tool_or_verifier_support is None
                else bool(tool_or_verifier_support)
            ),
            critical_claim_coverage=critical_claim_coverage,
            terminal_consistent=terminal_consistent,
            unresolved_critical_obligations=unresolved_critical,
            fatal_hard_fail=fatal_hard_fail,
        )


def _decision(
    candidate: CandidateSolution,
    status: str,
    unresolved: list[str],
    failed_obligations: list[str],
    failed_claims: list[str],
    hard_satisfied: list[str],
    model_reviewed: list[str],
    evidence_tier: str,
    closure,
    policy_assessment: CompletionAssessment | None = None,
) -> CompletionDecision:
    # ``VerificationClosure`` is the sole terminal authority.  The legacy
    # arguments remain in the function signature for trace compatibility, but
    # consumers must never observe a status that disagrees with the closure.
    status = closure.completion_status
    return CompletionDecision(
        candidate_id=candidate.candidate_id,
        status=status,
        unresolved_obligation_ids=unresolved,
        failed_obligation_ids=failed_obligations,
        failed_claim_ids=failed_claims,
        hard_satisfied_obligation_ids=hard_satisfied,
        model_reviewed_obligation_ids=model_reviewed,
        evidence_tier=evidence_tier,
        assurance_level=closure.assurance_level,
        conclusion_claim_id=closure.conclusion_claim_id,
        critical_claim_ids=list(closure.critical_claim_ids),
        unmapped_required_obligation_ids=list(
            closure.unmapped_required_obligation_ids
        ),
        supporting_evidence_ids=list(closure.supporting_evidence_ids),
        terminal_closure=closure.terminal_closure,
        assurance_reasons=list(closure.reasons),
        verification_closure=closure,
        policy_status=(
            policy_assessment.status if policy_assessment is not None else "legacy"
        ),
        policy_allowed=(
            policy_assessment.allowed if policy_assessment is not None else True
        ),
        best_available=(
            policy_assessment.best_available if policy_assessment is not None else False
        ),
        policy_reasons=(
            list(policy_assessment.reasons) if policy_assessment is not None else []
        ),
    )
