from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from mathforge.harness.schemas import CandidateSolution, Claim, EvidenceRecord
from mathforge.verification.repair_scope import failed_claim_ids, repair_impact_closure


RepairCallable = Callable[
    [CandidateSolution, list[str], list[EvidenceRecord]], CandidateSolution
]
ReverifyCallable = Callable[[CandidateSolution, list[str]], list[EvidenceRecord]]


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
        proposed, changed = self._merge_local_patch(candidate, proposed_patch, affected)
        if not changed:
            return RepairResult(candidate, proposed, True, True, affected, [], [], "no_local_change")
        try:
            new_evidence = reverify(proposed, affected)
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
        passed_failed_claims = {
            record.claim_id
            for record in new_evidence
            if record.candidate_id == proposed.candidate_id
            and record.claim_id in originally_failed
            and record.status == "pass"
            and record.strength == "hard"
        }
        if set(originally_failed) - passed_failed_claims:
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
            and record.status == "pass"
            and record.strength == "hard"
        }
        required_reverification = set(changed) | previously_verified
        passed_affected = {
            record.claim_id
            for record in new_evidence
            if record.candidate_id == proposed.candidate_id
            and record.claim_id in required_reverification
            and record.status == "pass"
            and record.strength == "hard"
        }
        if required_reverification - passed_affected:
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
        if any(
            record.claim_id is None
            and record.status == "fail"
            and record.strength == "hard"
            for record in new_evidence
        ):
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
        new_local = [record for record in new_evidence if record.claim_id in affected]
        old_local = self._local_evidence(candidate, evidence, affected)
        if self._evidence_quality(new_local) < self._evidence_quality(old_local):
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
        if any(record.status == "fail" and record.strength == "hard" for record in new_evidence):
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
        return RepairResult(
            proposed, proposed, True, False, affected, changed, new_evidence, "accepted"
        )

    @staticmethod
    def _local_evidence(
        candidate: CandidateSolution,
        evidence: list[EvidenceRecord],
        claim_ids: list[str],
    ) -> list[EvidenceRecord]:
        return [
            record
            for record in evidence
            if record.candidate_id == candidate.candidate_id and record.claim_id in claim_ids
        ]

    @staticmethod
    def _merge_local_patch(
        original: CandidateSolution,
        patch: CandidateSolution,
        affected: list[str],
    ) -> tuple[CandidateSolution, list[str]]:
        patch_by_id = {claim.claim_id: claim for claim in patch.claims}
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
        proposed = CandidateSolution(
            candidate_id=f"{original.candidate_id}-v{original.version + 1}",
            role=original.role,
            method=original.method,
            final_answer=patch.final_answer or original.final_answer,
            answer_type=original.answer_type,
            assumptions=list(original.assumptions),
            theorems=list(original.theorems),
            claims=merged_claims,
            solution_text=ClaimRepairService._rebuild_solution(
                merged_claims,
                patch.final_answer or original.final_answer,
            ),
            unresolved_obligations=list(original.unresolved_obligations),
            parse_status=patch.parse_status,
            version=original.version + 1,
            planned_method_family=original.planned_method_family,
            is_method_duplicate=original.is_method_duplicate,
            contract_deviations=sorted(
                set(original.contract_deviations)
                | {f"repair:{item}" for item in patch.contract_deviations}
            ),
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
        hard_fails = sum(record.strength == "hard" and record.status == "fail" for record in records)
        hard_passes = sum(record.strength == "hard" and record.status == "pass" for record in records)
        medium_passes = sum(
            record.strength == "medium" and record.status == "pass" for record in records
        )
        unknowns = sum(record.status in {"unknown", "error"} for record in records)
        return (-hard_fails, hard_passes, medium_passes, -unknowns)
