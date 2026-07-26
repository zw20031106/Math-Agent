from __future__ import annotations

from dataclasses import asdict, dataclass

from mathforge.harness.schemas import CandidateSolution, EvidenceRecord, ProofObligation
from mathforge.verification.capabilities import (
    VerificationCapability,
    capability_satisfies_obligation,
)
from mathforge.verification.evidence import (
    is_fatal_hard_failure,
    is_semantic_hard_pass,
)


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
            )

        unresolved: list[str] = []
        for obligation in obligations:
            if not obligation.required:
                continue
            source_claim_ids = set(obligation.source_claim_ids)
            matching_evidence = [
                record
                for record in own_evidence
                if record.status == "pass"
                and record.claim_id in source_claim_ids
                and obligation.obligation_id in record.payload.get("obligation_ids", [])
                and capability_satisfies_obligation(
                    record.capability,
                    obligation.kind,
                )
                and (
                    record.strength == "hard"
                    or (
                        record.strength == "soft"
                        and record.capability
                        == VerificationCapability.PROOF_OBLIGATION_REVIEW.value
                    )
                )
            ]
            if matching_evidence:
                obligation.status = "satisfied"
                obligation.satisfaction_evidence_ids = sorted(
                    record.evidence_id for record in matching_evidence
                )
            else:
                obligation.status = "unresolved"
                obligation.satisfaction_evidence_ids = []
                unresolved.append(obligation.obligation_id)

        candidate.unresolved_obligations = sorted(unresolved)
        return CompletionDecision(
            candidate.candidate_id,
            "incomplete" if unresolved else "complete",
            sorted(unresolved),
            [],
            [],
        )


def deterministic_degraded_candidates(
    candidates: list[CandidateSolution],
    evidence: list[EvidenceRecord],
    obligations: dict[str, list[ProofObligation]],
) -> list[CandidateSolution]:
    """Keep evidence-backed candidates when the optional LLM verifier is unavailable."""
    ranked: list[tuple[tuple[int, int, int], int, CandidateSolution]] = []
    for order, candidate in enumerate(candidates):
        own = [
            record
            for record in evidence
            if record.candidate_id == candidate.candidate_id
            and record.transaction_status == "active"
        ]
        if any(is_fatal_hard_failure(record) for record in own):
            continue
        own_obligations = obligations.get(candidate.candidate_id, [])
        if any(item.required and item.status == "failed" for item in own_obligations):
            continue
        semantic_passes = sum(
            is_semantic_hard_pass(record)
            for record in own
        )
        if semantic_passes == 0:
            continue
        satisfied = sum(
            item.required and item.status == "satisfied"
            for item in own_obligations
        )
        unresolved = sum(
            item.required and item.status != "satisfied"
            for item in own_obligations
        )
        ranked.append(
            ((-satisfied, -semantic_passes, unresolved), order, candidate)
        )
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in ranked]
