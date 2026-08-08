from __future__ import annotations

from dataclasses import asdict, dataclass

from mathforge.harness.schemas import CandidateSolution, EvidenceRecord, ProofObligation
from mathforge.verification.capabilities import (
    VerificationCapability,
    capability_satisfies_obligation,
)
from mathforge.verification.evidence import is_fatal_hard_failure


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

    def to_dict(self) -> dict:
        return asdict(self)


class ProofCompletionGate:
    """Require every required proof obligation to have mapped evidence."""

    def evaluate(
        self,
        candidate: CandidateSolution,
        evidence: list[EvidenceRecord],
        obligations: list[ProofObligation],
        *,
        response_mode: str = "answer_only",
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
            return CompletionDecision(
                candidate.candidate_id,
                "failed",
                list(candidate.unresolved_obligations),
                failed_obligations,
                failed_claims,
                [],
                [],
                "incomplete",
            )

        unresolved: list[str] = []
        hard_satisfied: list[str] = []
        model_reviewed: list[str] = []
        for obligation in obligations:
            if not obligation.required:
                continue
            source_claim_ids = set(obligation.source_claim_ids)
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
        return CompletionDecision(
            candidate.candidate_id,
            status,
            sorted(unresolved),
            [],
            [],
            sorted(hard_satisfied),
            sorted(model_reviewed),
            evidence_tier,
        )
