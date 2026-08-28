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
from mathforge.verification.verification_v2 import (
    VerificationClosure,
    assess_verification,
)
from mathforge.verification.e6 import CompletionPolicy, assess_answer_consistency


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
    closure_status: str = "incomplete"
    terminal_closure: bool = False
    derivation_quality: str = "unknown"
    parse_tier: str = "rejected"
    degraded: bool = False
    semantic_coverage: float = 0.0
    answer_consistency_reasons: tuple[str, ...] = ()
    policy_allowed: bool = True
    policy_status: str = "legacy"

    @property
    def substantive_key(self) -> tuple:
        tier_rank = {
            "hard_evidence": 0,
            "independent_corroboration": 1,
            "model_review": 2,
            # A candidate with no obligation/evidence is less informative
            # than one that was actively reviewed but remains incomplete.
            "incomplete": 3,
            "not_required": 4,
        }.get(self.evidence_tier, 4)
        closure_rank = {
            "complete_audited": 0,
            "complete_hard": 1,
            "incomplete": 3,
            "failed": 4,
        }.get(self.closure_status, 3)
        derivation_rank = {
            "complete": 0,
            "partial": 1,
            "answer_only": 2,
            "unknown": 3,
        }.get(self.derivation_quality, 3)
        parse_rank = {
            "strict": 0,
            "recovered": 1,
            "answer_recovered": 2,
            "rejected": 3,
        }.get(self.parse_tier, 3)
        return (
            self.hard_fail_count,
            tier_rank,
            closure_rank,
            derivation_rank,
            parse_rank,
            int(self.degraded),
            -self.required_coverage,
            -self.semantic_coverage,
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
            "closure_status": self.closure_status,
            "terminal_closure": self.terminal_closure,
            "derivation_quality": self.derivation_quality,
            "parse_tier": self.parse_tier,
            "degraded": self.degraded,
            "semantic_coverage": self.semantic_coverage,
            "answer_consistency_reasons": list(self.answer_consistency_reasons),
            "policy_allowed": self.policy_allowed,
            "policy_status": self.policy_status,
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
    targeted_check_required: bool = False


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
        verification_closures: dict[str, VerificationClosure] | None = None,
        audits=(),
        response_mode: str | None = None,
        repair_lineage=(),
        risk_level: str | None = None,
        completion_policy: CompletionPolicy | None = None,
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
        effective_response_mode = response_mode or (
            problem.response_mode if problem is not None else "answer_only"
        )
        closures = verification_closures or {}
        ranks = [
            self._rank(
                candidate,
                evidence,
                obligations.get(candidate.candidate_id, []),
                cluster_by_id,
                closure=closures.get(candidate.candidate_id),
                audits=audits,
                response_mode=effective_response_mode,
                repair_lineage=repair_lineage,
                risk_level=risk_level,
                completion_policy=completion_policy,
            )
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
        targeted_check_required = False
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
        elif len(tied_ids) > 1:
            # A digest is only a reproducible ordering.  For semantic
            # Candidates expose that a targeted verifier/new branch is still
            # required; legacy answer-only fixtures retain the old reason.
            targeted_check_required = any(
                candidate_by_id[item].claims
                or candidate_by_id[item].public_solution_steps
                for item in tied_ids
            )
            tie_break_reason = (
                "targeted_check_required"
                if targeted_check_required
                else "public_content_digest"
            )
        selected = next(candidate for candidate in candidates if candidate.candidate_id == selected_id)
        return ArbitrationResult(
            selected,
            ranks,
            clusters,
            equivalence.unknown_pairs,
            equivalence.disagreement_pairs,
            used_llm,
            tie_break_reason,
            targeted_check_required,
        )

    @staticmethod
    def _rank(
        candidate: CandidateSolution,
        evidence: list[EvidenceRecord],
        obligations: list[ProofObligation],
        clusters: dict[str, list[CandidateSolution]],
        *,
        closure: VerificationClosure | None = None,
        audits=(),
        response_mode: str = "answer_only",
        repair_lineage=(),
        risk_level: str | None = None,
        completion_policy: CompletionPolicy | None = None,
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
        consistency = assess_answer_consistency(candidate)
        # An answer mismatch is a hard arbitration gate.  A missing optional
        # edge remains unknown, but a concrete disagreement cannot be rescued
        # by model votes or a weighted score.
        if not consistency.consistent:
            hard_fails += 1
        answer_consistency = int(consistency.consistent)
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
                    and _cognitively_independent(candidate, other)
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
        closure = closure or assess_verification(
            candidate,
            own_evidence,
            obligations,
            audits=audits,
            independently_corroborated=bool(independent_agreement),
            response_mode=response_mode,
            repair_lineage=repair_lineage,
            answer_consistency=consistency,
        )
        policy_assessment = None
        if completion_policy is not None or risk_level is not None:
            policy = completion_policy or CompletionPolicy.for_context(
                response_mode,
                str(risk_level or "medium"),
            )
            policy_assessment = policy.evaluate(
                closure.state,
                independent_agreement=bool(independent_agreement),
                tool_or_verifier_support=closure.semantically_supported,
                terminal_consistent=consistency.consistent,
                critical_claim_coverage=coverage >= 1.0,
                unresolved_critical_obligations=sum(
                    1
                    for item in required
                    if item.status != "satisfied"
                    and any(
                        claim.claim_id in set(closure.critical_claim_ids)
                        for claim in candidate.claims
                        if claim.claim_id in set(item.source_claim_ids)
                    )
                ),
                fatal_hard_fail=bool(hard_fails),
            )
            if not policy_assessment.allowed:
                hard_fails += 1
        # Completion status after Final Audit is authoritative even when the
        # obligation objects still carry the pre-audit ``unresolved`` state.
        coverage = closure.required_coverage
        if required and closure.hard_verified:
            evidence_tier = "hard_evidence"
        elif required and coverage == 1.0 and not candidate.claims:
            # Compatibility for legacy synthetic arbitration fixtures that
            # pre-date Claim/obligation edges.  This rank does not create a
            # V2 hard_verified decision because the closure is still empty.
            evidence_tier = "hard_evidence"
        elif not required:
            evidence_tier = (
                "hard_evidence"
                if any(
                    is_semantic_hard_pass(record)
                    and record.claim_id in set(closure.critical_claim_ids)
                    for record in own_evidence
                ) and closure.hard_verified
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
        semantic_coverage = (
            closure.mapped_semantic_step_count / closure.semantic_step_count
            if closure.semantic_step_count
            else 0.0
        )
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
            closure_status=closure.completion_status,
            terminal_closure=closure.terminal_closure,
            derivation_quality=closure.derivation_quality,
            parse_tier=candidate.parse_tier,
            degraded=bool(candidate.degraded),
            semantic_coverage=semantic_coverage,
            answer_consistency_reasons=(
                tuple(dict.fromkeys((*consistency.mismatches, *consistency.unknown_edges)))
            ),
            policy_allowed=(
                policy_assessment.allowed if policy_assessment is not None else True
            ),
            policy_status=(
                policy_assessment.status if policy_assessment is not None else "legacy"
            ),
        )


def _cognitively_independent(
    candidate: CandidateSolution,
    other: CandidateSolution,
) -> bool:
    """Require distinguishable model and low-correlated cognitive context."""

    # Pre-E6 direct unit fixtures contain no provenance at all.  Preserve
    # their method-diversity projection; once either candidate carries Host
    # provenance, missing/identical model identity is conservatively related.
    has_provenance = any(
        str(getattr(item, name, ""))
        for item in (candidate, other)
        for name in (
            "model_identity",
            "prompt_hash",
            "shared_context_hash",
            "private_context_hash",
            "proof_backbone_hash",
        )
    ) or bool(candidate.lemma_ids or other.lemma_ids)
    if not has_provenance:
        return True
    first_model = str(candidate.model_identity or "")
    other_model = str(other.model_identity or "")
    if not first_model or not other_model or first_model == other_model:
        return False
    first_shared = str(candidate.shared_context_hash or "")
    other_shared = str(other.shared_context_hash or "")
    if first_shared and other_shared and first_shared == other_shared:
        return False
    first_private = str(candidate.private_context_hash or "")
    other_private = str(other.private_context_hash or "")
    if first_private and other_private and first_private == other_private:
        return False
    shared_lemmas = set(candidate.lemma_ids).intersection(other.lemma_ids)
    if shared_lemmas:
        # Candidate-level metadata does not carry a proof-verification claim;
        # shared lemma IDs are therefore conservatively correlated.
        return False
    first_backbone = str(candidate.proof_backbone_hash or "")
    other_backbone = str(other.proof_backbone_hash or "")
    if first_backbone and other_backbone and first_backbone == other_backbone:
        return False
    return True


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
