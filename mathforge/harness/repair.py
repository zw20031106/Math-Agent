from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from mathforge.context.claim_graph import ClaimGraph
from mathforge.harness.schemas import (
    CandidatePatch,
    CandidateSolution,
    CandidateSource,
    Claim,
    EvidenceRecord,
)
from mathforge.verification.repair_scope import (
    claim_impact_closure,
    failed_claim_ids,
    repair_impact_closure,
)
from mathforge.verification.evidence import (
    is_fatal_hard_failure,
    is_semantic_hard_pass,
)
from mathforge.verification.admission import CandidateAdmissionError


RepairCallable = Callable[
    [CandidateSolution, list[str], list[EvidenceRecord]],
    CandidatePatch | CandidateSolution,
]
ReverifyCallable = Callable[[CandidateSolution, list[str]], list[EvidenceRecord]]
AcceptanceCallable = Callable[
    [CandidateSolution, list[EvidenceRecord]],
    tuple[bool, str],
]


@dataclass
class RepairResult:
    selected: CandidateSolution
    proposed: CandidateSolution | None
    triggered: bool
    rolled_back: bool
    affected_claim_ids: list[str]
    changed_claim_ids: list[str]
    new_evidence: list[EvidenceRecord]
    reason: str

    @property
    def transaction_steps(self) -> tuple[str, ...]:
        if not self.triggered:
            return ("detect",)
        terminal = "rollback" if self.rolled_back else "commit"
        return ("detect", "scope", "patch", "reverify", "compare", terminal)

    @property
    def transaction_status(self) -> str:
        if not self.triggered:
            return "not_started"
        return "rolled_back" if self.rolled_back else "committed"

    def to_dict(self) -> dict:
        return {
            "selected_candidate_id": self.selected.candidate_id,
            "proposed_candidate_id": self.proposed.candidate_id if self.proposed else None,
            "triggered": self.triggered,
            "rolled_back": self.rolled_back,
            "affected_claim_ids": list(self.affected_claim_ids),
            "changed_claim_ids": list(self.changed_claim_ids),
            "new_evidence": [record.to_dict() for record in self.new_evidence],
            "reason": self.reason,
            "transaction_steps": list(self.transaction_steps),
            "transaction_status": self.transaction_status,
        }


class ClaimRepairService:
    def __init__(self, max_total_repairs: int = 2) -> None:
        self._max_total_repairs = max_total_repairs
        self._repaired_candidates: set[str] = set()
        self._total_repairs = 0

    def attempt(
        self,
        candidate: CandidateSolution,
        evidence: list[EvidenceRecord],
        *,
        repair: RepairCallable,
        reverify: ReverifyCallable,
    ) -> RepairResult:
        originally_failed = failed_claim_ids(candidate.candidate_id, evidence)
        affected = repair_impact_closure(candidate, evidence)
        if not affected:
            return RepairResult(candidate, None, False, False, [], [], [], "no_hard_claim_failure")
        if candidate.candidate_id in self._repaired_candidates:
            return RepairResult(candidate, None, False, False, affected, [], [], "candidate_limit")
        if self._total_repairs >= self._max_total_repairs:
            return RepairResult(candidate, None, False, False, affected, [], [], "problem_limit")
        self._repaired_candidates.add(candidate.candidate_id)
        self._total_repairs += 1
        try:
            proposed_patch = repair(
                candidate,
                affected,
                self._local_evidence(candidate, evidence, affected),
            )
        except Exception:
            return RepairResult(
                candidate, None, True, True, affected, [], [], "repair_agent_failed"
            )
        try:
            proposed, changed = self._merge_local_patch(
                candidate,
                proposed_patch,
                affected,
            )
        except (TypeError, ValueError):
            return RepairResult(
                candidate,
                None,
                True,
                True,
                affected,
                [],
                [],
                "invalid_repair_graph",
            )
        if not changed:
            return RepairResult(candidate, proposed, True, True, affected, [], [], "no_local_change")
        affected = sorted(
            set(affected)
            | set(claim_impact_closure(proposed, originally_failed))
        )
        if proposed.final_answer != candidate.final_answer:
            terminal_claim_ids = {
                claim_id.rsplit("::", 1)[-1]
                for claim_id in ClaimGraph.from_candidate(
                    proposed
                ).terminal_claim_ids(proposed.candidate_id)
            }
            if not terminal_claim_ids.intersection(affected):
                return RepairResult(
                    candidate,
                    proposed,
                    True,
                    True,
                    affected,
                    changed,
                    [],
                    "final_answer_dependency_missing",
                )
        for claim in proposed.claims:
            if claim.claim_id in affected:
                claim.status = "unverified"
                claim.verification_state = "unknown"
        try:
            new_evidence = reverify(proposed, affected)
        except CandidateAdmissionError:
            return RepairResult(
                candidate,
                proposed,
                True,
                True,
                affected,
                changed,
                [],
                "candidate_validation_failed",
            )
        except Exception:
            return RepairResult(
                candidate,
                proposed,
                True,
                True,
                affected,
                changed,
                [],
                "reverification_failed",
            )
        if not new_evidence:
            return RepairResult(
                candidate, proposed, True, True, affected, changed, [], "reverification_missing"
            )
        if any(
            record.claim_id is None
            and record.transaction_status == "active"
            and record.status == "fail"
            and record.strength == "hard"
            for record in new_evidence
        ):
            self._mark_transaction(new_evidence, "rejected")
            return RepairResult(
                candidate,
                proposed,
                True,
                True,
                affected,
                changed,
                new_evidence,
                "candidate_validation_failed",
            )
        passed_failed_claims = {
            record.claim_id
            for record in new_evidence
            if record.candidate_id == proposed.candidate_id
            and record.claim_id in originally_failed
            and is_semantic_hard_pass(record)
        }
        if set(originally_failed) - passed_failed_claims:
            self._mark_transaction(new_evidence, "rejected")
            return RepairResult(
                candidate,
                proposed,
                True,
                True,
                affected,
                changed,
                new_evidence,
                "failed_claim_not_reverified",
            )
        previously_verified = {
            claim.claim_id
            for claim in candidate.claims
            if claim.claim_id in affected and claim.status == "verified"
        } | {
            record.claim_id
            for record in evidence
            if record.candidate_id == candidate.candidate_id
            and record.claim_id in affected
            and is_semantic_hard_pass(record)
        }
        required_reverification = set(changed) | previously_verified
        passed_affected = {
            record.claim_id
            for record in new_evidence
            if record.candidate_id == proposed.candidate_id
            and record.claim_id in required_reverification
            and is_semantic_hard_pass(record)
        }
        if required_reverification - passed_affected:
            self._mark_transaction(new_evidence, "rejected")
            return RepairResult(
                candidate,
                proposed,
                True,
                True,
                affected,
                changed,
                new_evidence,
                "affected_claim_not_reverified",
            )
        new_local = [record for record in new_evidence if record.claim_id in affected]
        old_local = self._local_evidence(candidate, evidence, affected)
        if self._evidence_quality(new_local) < self._evidence_quality(old_local):
            self._mark_transaction(new_evidence, "rejected")
            return RepairResult(
                candidate,
                proposed,
                True,
                True,
                affected,
                changed,
                new_evidence,
                "evidence_quality_decreased",
            )
        if any(is_fatal_hard_failure(record) for record in new_evidence):
            self._mark_transaction(new_evidence, "rejected")
            return RepairResult(
                candidate,
                proposed,
                True,
                True,
                affected,
                changed,
                new_evidence,
                "hard_failure_remains",
            )
        self._mark_transaction(new_evidence, "active")
        return RepairResult(
            proposed, proposed, True, False, affected, changed, new_evidence, "accepted"
        )

    def attempt_for_trigger(
        self,
        candidate: CandidateSolution,
        evidence: list[EvidenceRecord],
        trigger_claim_ids: list[str],
        *,
        repair: RepairCallable,
        reverify: ReverifyCallable,
        accept: AcceptanceCallable,
    ) -> RepairResult:
        valid_claim_ids = {claim.claim_id for claim in candidate.claims}
        roots = sorted(set(trigger_claim_ids).intersection(valid_claim_ids))
        affected = claim_impact_closure(candidate, roots)
        if not affected:
            return RepairResult(
                candidate,
                None,
                False,
                False,
                [],
                [],
                [],
                "no_verifier_trigger",
            )
        if candidate.candidate_id in self._repaired_candidates:
            return RepairResult(
                candidate,
                None,
                False,
                False,
                affected,
                [],
                [],
                "candidate_limit",
            )
        if self._total_repairs >= self._max_total_repairs:
            return RepairResult(
                candidate,
                None,
                False,
                False,
                affected,
                [],
                [],
                "problem_limit",
            )
        self._repaired_candidates.add(candidate.candidate_id)
        self._total_repairs += 1
        try:
            patch = repair(
                candidate,
                affected,
                self._local_evidence(candidate, evidence, affected),
            )
            proposed, changed = self._merge_local_patch(
                candidate,
                patch,
                affected,
            )
        except Exception:
            return RepairResult(
                candidate,
                None,
                True,
                True,
                affected,
                [],
                [],
                "repair_agent_failed",
            )
        if not changed:
            return RepairResult(
                candidate,
                proposed,
                True,
                True,
                affected,
                [],
                [],
                "no_local_change",
            )
        if proposed.final_answer != candidate.final_answer:
            terminal_claim_ids = {
                claim_id.rsplit("::", 1)[-1]
                for claim_id in ClaimGraph.from_candidate(
                    proposed
                ).terminal_claim_ids(proposed.candidate_id)
            }
            if not terminal_claim_ids.intersection(affected):
                return RepairResult(
                    candidate,
                    proposed,
                    True,
                    True,
                    affected,
                    changed,
                    [],
                    "final_answer_dependency_missing",
                )
        try:
            new_evidence = reverify(proposed, affected)
        except CandidateAdmissionError:
            return RepairResult(
                candidate,
                proposed,
                True,
                True,
                affected,
                changed,
                [],
                "candidate_validation_failed",
            )
        except Exception:
            return RepairResult(
                candidate,
                proposed,
                True,
                True,
                affected,
                changed,
                [],
                "reverification_failed",
            )
        if any(
            record.claim_id is None
            and record.transaction_status == "active"
            and record.status == "fail"
            and record.strength == "hard"
            for record in new_evidence
        ):
            self._mark_transaction(new_evidence, "rejected")
            return RepairResult(
                candidate,
                proposed,
                True,
                True,
                affected,
                changed,
                new_evidence,
                "candidate_validation_failed",
            )
        accepted, reason = accept(proposed, new_evidence)
        if not accepted:
            self._mark_transaction(new_evidence, "rejected")
            return RepairResult(
                candidate,
                proposed,
                True,
                True,
                affected,
                changed,
                new_evidence,
                reason,
            )
        self._mark_transaction(new_evidence, "active")
        return RepairResult(
            proposed,
            proposed,
            True,
            False,
            affected,
            changed,
            new_evidence,
            reason,
        )

    @staticmethod
    def _mark_transaction(
        records: list[EvidenceRecord],
        status: str,
    ) -> None:
        for record in records:
            record.transaction_status = status

    @staticmethod
    def _local_evidence(
        candidate: CandidateSolution,
        evidence: list[EvidenceRecord],
        claim_ids: list[str],
    ) -> list[EvidenceRecord]:
        return [
            record
            for record in evidence
            if record.candidate_id == candidate.candidate_id
            and record.claim_id in claim_ids
            and record.transaction_status == "active"
        ]

    @staticmethod
    def _merge_local_patch(
        original: CandidateSolution,
        patch: CandidatePatch | CandidateSolution,
        affected: list[str],
    ) -> tuple[CandidateSolution, list[str]]:
        if isinstance(patch, CandidatePatch):
            patch.validate()
            patch_claims = patch.replacement_claims
            patch_final_answer = patch.final_answer
            patch_status = patch.parse_status
            patch_deviations = patch.contract_deviations
            patch_public_steps = patch.public_solution_steps
            patch_unresolved = patch.unresolved_obligations
        else:
            patch_claims = patch.claims
            patch_final_answer = patch.final_answer
            patch_status = patch.parse_status
            patch_deviations = patch.contract_deviations
            patch_public_steps = patch.public_solution_steps
            patch_unresolved = patch.unresolved_obligations
        patch_by_id = {claim.claim_id: claim for claim in patch_claims}
        changed: list[str] = []
        merged_claims: list[Claim] = []
        for claim in original.claims:
            replacement = patch_by_id.get(claim.claim_id) if claim.claim_id in affected else None
            if replacement is not None and replacement.to_dict() != claim.to_dict():
                merged_claims.append(
                    Claim(
                        replacement.claim_id,
                        replacement.statement,
                        list(replacement.depends_on),
                        replacement.check_type,
                        replacement.importance,
                        "unverified",
                        replacement.claim_kind,
                        "unknown",
                    )
                )
                changed.append(claim.claim_id)
            else:
                merged_claims.append(
                    Claim(
                        claim.claim_id,
                        claim.statement,
                        list(claim.depends_on),
                        claim.check_type,
                        claim.importance,
                        "unverified" if claim.claim_id in affected else claim.status,
                        claim.claim_kind,
                        (
                            "unknown"
                            if claim.claim_id in affected
                            else claim.verification_state
                        ),
                    )
                )
        rebuilt_solution = ClaimRepairService._rebuild_solution(
            merged_claims,
            patch_final_answer or original.final_answer,
        )
        proposed = CandidateSolution(
            candidate_id=f"{original.candidate_id}-v{original.version + 1}",
            role=original.role,
            method=original.method,
            final_answer=patch_final_answer or original.final_answer,
            answer_type=original.answer_type,
            assumptions=list(original.assumptions),
            theorems=list(original.theorems),
            claims=merged_claims,
            public_solution_steps=(
                list(patch_public_steps)
                if patch_public_steps
                else [
                    claim.statement
                    for claim in merged_claims
                    if claim.statement.strip()
                ]
            ),
            solution_text=rebuilt_solution,
            unresolved_obligations=(
                list(patch_unresolved)
                if patch_unresolved
                else list(original.unresolved_obligations)
            ),
            parse_status=patch_status,
            version=original.version + 1,
            planned_method_family=original.planned_method_family,
            is_method_duplicate=original.is_method_duplicate,
            contract_deviations=sorted(
                set(original.contract_deviations)
                | {f"repair:{item}" for item in patch_deviations}
            ),
            method_steps=list(original.method_steps),
            source=CandidateSource.LLM_REPAIR.value,
            parse_tier=original.parse_tier,
            degraded=original.degraded,
            assurance=original.assurance,
            method_family=original.method_family,
            shared_context_hash=original.shared_context_hash,
            private_context_hash=original.private_context_hash,
            skill_set_hash=original.skill_set_hash,
            lemma_ids=list(original.lemma_ids),
            proof_backbone_hash=original.proof_backbone_hash,
            model_identity=original.model_identity,
            prompt_hash=original.prompt_hash,
            branch_id=original.branch_id,
            branch_context_hash=original.branch_context_hash,
        )
        proposed.validate()
        return proposed, changed

    @staticmethod
    def _rebuild_solution(claims: list[Claim], final_answer: str) -> str:
        lines = ["Claim sequence:"]
        for index, claim in enumerate(claims, start=1):
            dependencies = (
                f" (depends on: {', '.join(claim.depends_on)})" if claim.depends_on else ""
            )
            lines.append(f"{index}. [{claim.claim_id}] {claim.statement}{dependencies}")
        if final_answer.strip():
            lines.extend(["", f"Final answer: {final_answer.strip()}"])
        return "\n".join(lines)

    @staticmethod
    def _evidence_quality(records: list[EvidenceRecord]) -> tuple[int, int, int, int]:
        records = [
            record
            for record in records
            if record.transaction_status == "active"
        ]
        hard_fails = sum(is_fatal_hard_failure(record) for record in records)
        hard_passes = sum(is_semantic_hard_pass(record) for record in records)
        medium_passes = sum(
            record.strength == "medium" and record.status == "pass" for record in records
        )
        unknowns = sum(record.status in {"unknown", "error"} for record in records)
        return (-hard_fails, hard_passes, medium_passes, -unknowns)
