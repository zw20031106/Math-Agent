from __future__ import annotations

from dataclasses import dataclass
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
    soft_score: int

    @property
    def lexicographic_key(self) -> tuple:
        return (
            self.hard_fail_count,
            -self.required_coverage,
            -self.answer_consistency,
            -self.independent_agreement,
            -self.soft_score,
        )

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "hard_fail_count": self.hard_fail_count,
            "required_coverage": self.required_coverage,
            "answer_consistency": self.answer_consistency,
            "independent_agreement": self.independent_agreement,
            "soft_score": self.soft_score,
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
        order = {candidate.candidate_id: index for index, candidate in enumerate(candidates)}
        ranks.sort(key=lambda rank: (rank.lexicographic_key, order[rank.candidate_id]))
        best_key = ranks[0].lexicographic_key
        tied_ids = [rank.candidate_id for rank in ranks if rank.lexicographic_key == best_key]
        used_llm = False
        selected_id = tied_ids[0]
        if len(tied_ids) > 1 and llm_arbiter is not None:
            proposed = llm_arbiter(
                [candidate for candidate in candidates if candidate.candidate_id in tied_ids]
            )
            if proposed in tied_ids:
                selected_id = proposed
                used_llm = True
        selected = next(candidate for candidate in candidates if candidate.candidate_id == selected_id)
        return ArbitrationResult(
            selected,
            ranks,
            clusters,
            equivalence.unknown_pairs,
            equivalence.disagreement_pairs,
            used_llm,
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
            record.status == "fail" and record.strength == "hard" for record in own_evidence
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
        return CandidateRank(
            candidate.candidate_id,
            hard_fails,
            coverage,
            answer_consistency,
            independent_agreement,
            soft_score,
        )
