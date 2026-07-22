from __future__ import annotations

from dataclasses import dataclass

from mathforge.harness.schemas import CandidateSolution, EvidenceRecord, LemmaCard, ProofObligation


@dataclass(frozen=True)
class VerificationFinding:
    candidate_id: str
    status: str
    failed_claim_ids: list[str]
    unresolved_obligation_ids: list[str]


class VerifierSkeptic:
    """Build a conservative verdict from deterministic evidence and obligations."""

    def review(
        self,
        candidate: CandidateSolution,
        evidence: list[EvidenceRecord],
        obligations: list[ProofObligation],
    ) -> VerificationFinding:
        failed_claim_ids = sorted(
            {
                record.claim_id
                for record in evidence
                if record.candidate_id == candidate.candidate_id
                and record.claim_id is not None
                and record.status == "fail"
                and record.strength == "hard"
            }
        )
        unresolved = [
            obligation.obligation_id
            for obligation in obligations
            if obligation.required and obligation.status != "satisfied"
        ]
        if failed_claim_ids or any(item.status == "failed" for item in obligations):
            status = "failed"
        elif unresolved:
            status = "incomplete"
        else:
            status = "verified"
        return VerificationFinding(candidate.candidate_id, status, failed_claim_ids, unresolved)


class LemmaVerifier:
    def verify(
        self,
        lemma: LemmaCard,
        candidates: list[CandidateSolution],
        evidence: list[EvidenceRecord],
    ) -> LemmaCard:
        source = lemma.proof_sketch.removeprefix("Extracted from ")
        candidate_id, separator, claim_id = source.partition(":")
        matching = [
            record
            for record in evidence
            if record.candidate_id == candidate_id and record.claim_id == claim_id
        ]
        if any(record.status == "fail" and record.strength == "hard" for record in matching):
            lemma.status = "rejected"
        elif any(record.status == "pass" and record.strength == "hard" for record in matching):
            lemma.status = "verified"
        else:
            claim = next(
                (
                    claim
                    for candidate in candidates
                    if candidate.candidate_id == candidate_id
                    for claim in candidate.claims
                    if claim.claim_id == claim_id
                ),
                None,
            )
            if claim is not None and claim.status == "verified":
                lemma.status = "verified"
            elif claim is not None and claim.status == "rejected":
                lemma.status = "rejected"
            else:
                lemma.status = "conflicted"
        lemma.evidence_ids = [record.evidence_id for record in matching]
        return lemma
