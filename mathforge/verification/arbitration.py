from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Callable

from mathforge.harness.budget import CallBudget
from mathforge.harness.schemas import (
    CandidateSolution,
    EvidenceRecord,
    ProblemIR,
    ProofObligation,
)
from mathforge.tools.executor import ToolExecutor
from mathforge.verification.equivalence import analyze_equivalence
from mathforge.verification.evidence import (
    is_fatal_hard_failure,
    is_semantic_hard_pass,
)
from mathforge.verification.methods import (
    candidate_method_signature,
    method_contract_valid,
)


@dataclass(frozen=True)
class CandidateRank:
    candidate_id: str
    hard_fail_count: int
    required_coverage: float
    answer_consistency: int
    independent_agreement: int
    evidence_tier: str
    review_support: int
    soft_score: int
    deterministic_tie_break: str

    @property
    def substantive_key(self) -> tuple:
        tier_rank = {
            "hard_evidence": 0,
            "independent_corroboration": 1,
            "model_review": 2,
            "not_required": 3,
            "incomplete": 4,
        }.get(self.evidence_tier, 4)
        return (
            self.hard_fail_count,
            tier_rank,
            -self.required_coverage,
            -self.answer_consistency,
            -self.independent_agreement,
            -self.review_support,
            -self.soft_score,
        )

    @property
    def lexicographic_key(self) -> tuple:
        return (*self.substantive_key, self.deterministic_tie_break)

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "hard_fail_count": self.hard_fail_count,
            "required_coverage": self.required_coverage,
            "answer_consistency": self.answer_consistency,
            "independent_agreement": self.independent_agreement,
            "evidence_tier": self.evidence_tier,
            "review_support": self.review_support,
            "soft_score": self.soft_score,
            "deterministic_tie_break": self.deterministic_tie_break,
            "substantive_key": list(self.substantive_key),
            "lexicographic_key": list(self.lexicographic_key),
        }


@dataclass
class ArbitrationResult:
    selected: CandidateSolution
    ranks: list[CandidateRank]
    clusters: list[list[str]]
    unknown_pairs: list[tuple[str, str]]
    disagreement_pairs: list[tuple[str, str]]
    used_llm_arbiter: bool = False
    tie_break_reason: str = "evidence_rank"


class ArbitrationPolicy:
    def __init__(self, tool_executor: ToolExecutor | None = None) -> None:
        self._tools = tool_executor or ToolExecutor()

    def select(
        self,
        candidates: list[CandidateSolution],
        evidence: list[EvidenceRecord],
        obligations: dict[str, list[ProofObligation]],
        *,
        llm_arbiter: Callable[[list[CandidateSolution]], str] | None = None,
        budget: CallBudget | None = None,
        problem: ProblemIR | None = None,
    ) -> ArbitrationResult:
        if not candidates:
            raise ValueError("at least one candidate is required")
        equivalence = analyze_equivalence(
            candidates,
            problem,
            self._tools,
            budget,
        )
        clusters = equivalence.clusters
        candidate_by_id = {candidate.candidate_id: candidate for candidate in candidates}
        cluster_by_id = {
            candidate_id: [candidate_by_id[item] for item in cluster]
            for cluster in clusters
            for candidate_id in cluster
        }
        ranks = [
            self._rank(candidate, evidence, obligations.get(candidate.candidate_id, []), cluster_by_id)
            for candidate in candidates
        ]
        ranks.sort(key=lambda rank: rank.lexicographic_key)
        best_key = ranks[0].substantive_key
        tied_ids = [
            rank.candidate_id
            for rank in ranks
            if rank.substantive_key == best_key
        ]
        used_llm = False
        selected_id = ranks[0].candidate_id
        tie_break_reason = (
            "evidence_rank"
            if len(tied_ids) == 1
            else "public_content_digest"
        )
        if len(tied_ids) > 1 and llm_arbiter is not None:
            proposed = llm_arbiter(
                [candidate for candidate in candidates if candidate.candidate_id in tied_ids]
            )
            if proposed in tied_ids:
                selected_id = proposed
                used_llm = True
                tie_break_reason = "llm_arbiter"
        selected = next(candidate for candidate in candidates if candidate.candidate_id == selected_id)
        return ArbitrationResult(
            selected,
            ranks,
            clusters,
            equivalence.unknown_pairs,
            equivalence.disagreement_pairs,
            used_llm,
            tie_break_reason,
        )

    @staticmethod
    def _rank(
        candidate: CandidateSolution,
        evidence: list[EvidenceRecord],
        obligations: list[ProofObligation],
        clusters: dict[str, list[CandidateSolution]],
    ) -> CandidateRank:
        own_evidence = [
            record
            for record in evidence
            if record.candidate_id == candidate.candidate_id
            and record.transaction_status == "active"
        ]
        hard_fails = sum(
            is_fatal_hard_failure(record) for record in own_evidence
        )
        required = [obligation for obligation in obligations if obligation.required]
        coverage = (
            sum(obligation.status == "satisfied" for obligation in required) / len(required)
            if required
            else 1.0
        )
        answer_consistency = int(bool(candidate.final_answer.strip()))
        cluster = clusters.get(candidate.candidate_id, [candidate])
        own_signature = candidate_method_signature(candidate)
        independent_agreement = (
            0
            if candidate.is_method_duplicate or not method_contract_valid(candidate)
            else len(
                {
                    candidate_method_signature(other)
                    for other in cluster
                    if other.candidate_id != candidate.candidate_id
                    and not other.is_method_duplicate
                    and method_contract_valid(other)
                    and candidate_method_signature(other) != own_signature
                }
            )
        )
        soft_score = sum(
            1 if record.status == "pass" else -1 if record.status == "fail" else 0
            for record in own_evidence
            if record.strength != "hard"
        )
        review_support = sum(
            1 if record.status == "pass" else -1
            if record.status == "fail" else 0
            for record in own_evidence
            if record.evidence_type == "llm:VerifierSkeptic"
            and record.payload.get("review_target_ids")
        )
        model_reviewed = any(
            record.evidence_type == "llm:VerifierSkeptic"
            and record.status == "pass"
            for record in own_evidence
        )
        targeted_review_present = any(
            record.evidence_type == "llm:VerifierSkeptic"
            and record.payload.get("review_target_ids")
            for record in own_evidence
        )
        if required and coverage == 1.0:
            evidence_tier = "hard_evidence"
        elif not required:
            evidence_tier = (
                "hard_evidence"
                if any(
                    is_semantic_hard_pass(record)
                    for record in own_evidence
                )
                else (
                    "independent_corroboration"
                    if independent_agreement
                    else (
                        "model_review"
                        if model_reviewed
                        else (
                            "incomplete"
                            if targeted_review_present
                            else "not_required"
                        )
                    )
                )
            )
        elif independent_agreement:
            evidence_tier = "independent_corroboration"
        elif model_reviewed:
            evidence_tier = "model_review"
        else:
            evidence_tier = "incomplete"
        return CandidateRank(
            candidate_id=candidate.candidate_id,
            hard_fail_count=hard_fails,
            required_coverage=coverage,
            answer_consistency=answer_consistency,
            independent_agreement=independent_agreement,
            evidence_tier=evidence_tier,
            review_support=review_support,
            soft_score=soft_score,
            deterministic_tie_break=_candidate_digest(candidate),
        )


def _candidate_digest(candidate: CandidateSolution) -> str:
    payload = {
        "answer": candidate.final_answer,
        "answer_type": candidate.answer_type,
        "method": candidate_method_signature(candidate),
        "assumptions": sorted(candidate.assumptions),
        "critical_claims": sorted(
            claim.statement
            for claim in candidate.claims
            if claim.importance == "critical"
        ),
        "public_solution_steps": list(candidate.public_solution_steps),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return sha256(canonical).hexdigest()
