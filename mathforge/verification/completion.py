from __future__ import annotations

from dataclasses import asdict, dataclass

from mathforge.harness.schemas import CandidateSolution, EvidenceRecord, ProofObligation


@dataclass(frozen=True)
class CompletionDecision:
    candidate_id: str
    status: str
    unresolved_obligation_ids: list[str]
    failed_obligation_ids: list[str]
    failed_claim_ids: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


class ProofCompletionGate:
    """Require every required proof obligation to have mapped evidence."""

    def evaluate(
        self,
        candidate: CandidateSolution,
        evidence: list[EvidenceRecord],
        obligations: list[ProofObligation],
    ) -> CompletionDecision:
        own_evidence = [
            record for record in evidence if record.candidate_id == candidate.candidate_id
        ]
        failed_claims = sorted(
            {
                record.claim_id
                for record in own_evidence
                if record.claim_id is not None
                and record.status == "fail"
                and record.strength == "hard"
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
            )

        hard_passed_claims = {
            record.claim_id
            for record in own_evidence
            if record.claim_id is not None
            and record.status == "pass"
            and record.strength == "hard"
        }
        verified_claims = {
            claim.claim_id for claim in candidate.claims if claim.status == "verified"
        }
        unresolved: list[str] = []
        for obligation in obligations:
            if not obligation.required:
                continue
            source_claim_ids = set(obligation.source_claim_ids)
            hard_satisfied = bool(
                source_claim_ids & (hard_passed_claims | verified_claims)
            )
            soft_satisfied = any(
                record.evidence_type == "llm:VerifierSkeptic"
                and record.status == "pass"
                and record.claim_id in source_claim_ids
                and obligation.obligation_id in record.payload.get("obligation_ids", [])
                for record in own_evidence
            )
            if hard_satisfied or soft_satisfied:
                obligation.status = "satisfied"
            else:
                obligation.status = "unresolved"
                unresolved.append(obligation.obligation_id)

        candidate.unresolved_obligations = sorted(unresolved)
        return CompletionDecision(
            candidate.candidate_id,
            "incomplete" if unresolved else "complete",
            sorted(unresolved),
            [],
            [],
        )
