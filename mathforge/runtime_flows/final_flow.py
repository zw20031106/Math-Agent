from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from mathforge.verification.completion import CompletionDecision
from mathforge.verification.verification_v2 import VerificationClosure, assess_verification


PROOF_STATUSES = frozenset(
    {"complete_hard", "complete_audited", "incomplete", "failed"}
)


@dataclass(frozen=True)
class FinalProofStatus:
    candidate_id: str
    status: str
    reason_code: str
    audit_id: str = ""
    degraded: bool = False
    assurance_level: str = "candidate_valid"
    terminal_closure: bool = False
    verification_closure: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FinalProofStatusService:
    """Combine hard evidence and a version-matched Final Audit.

    Peer review and verifier opinions are useful soft evidence, but never by
    themselves upgrade a proof to a completed state. A committed repair also
    requires a later audit of the repaired Candidate version.
    """

    def finalize(
        self,
        candidate: Any,
        decision: CompletionDecision,
        *,
        obligations: Iterable[Any] = (),
        audits: Iterable[Any] = (),
        repaired: bool = False,
        response_mode: str = "answer_only",
        evidence: Iterable[Any] = (),
        repair_lineage: Iterable[dict[str, Any]] = (),
        closure: VerificationClosure | None = None,
    ) -> FinalProofStatus:
        candidate_id = str(candidate.candidate_id)

        if closure is None:
            closure = getattr(decision, "verification_closure", None)
        # Runtime passes the post-audit closure explicitly so every downstream
        # consumer observes the same immutable snapshot.  Only legacy callers
        # that omit it need a local reconstruction from evidence.
        if closure is None and evidence:
            closure = assess_verification(
                candidate,
                evidence,
                obligations,
                audits=audits,
                response_mode=response_mode,
                repaired=repaired,
                repair_lineage=repair_lineage,
            )

        def status(
            value: str,
            reason: str,
            audit_id: str = "",
            degraded: bool = False,
            assurance_level: str | None = None,
            terminal_closure: bool | None = None,
        ) -> FinalProofStatus:
            return FinalProofStatus(
                candidate_id,
                value,
                reason,
                audit_id,
                degraded,
                assurance_level or (
                    closure.assurance_level
                    if closure is not None
                    else decision.assurance_level
                ),
                terminal_closure
                if terminal_closure is not None
                else (
                    closure.terminal_closure
                    if closure is not None
                    else decision.terminal_closure
                ),
                closure.to_dict() if closure is not None else None,
            )

        if closure is not None and closure.completion_status == "failed":
            return status("failed", "hard_evidence_failed")
        if not self._proof_shape_complete(candidate, response_mode, closure):
            return status(
                "incomplete",
                "proof_full_steps_missing",
                degraded=True,
            )

        required = [item for item in obligations if bool(item.required)]
        all_covered = all(
            str(item.status) in {"satisfied", "reviewed"}
            for item in required
        )
        matching_audit = next(
            (
                item
                for item in reversed(tuple(audits))
                if str(item.candidate_id) == candidate_id
                and int(item.candidate_version) == int(candidate.version)
            ),
            None,
        )
        if closure is not None and closure.audit_id:
            matching_audit = next(
                (
                    item
                    for item in reversed(tuple(audits))
                    if str(getattr(item, "audit_id", "")) == closure.audit_id
                ),
                matching_audit,
            )
        if matching_audit is not None:
            if matching_audit.status == "failed":
                return status(
                    "failed",
                    "final_audit_failed",
                    str(matching_audit.audit_id),
                )
            if (
                matching_audit.status in {"complete_audited", "complete_hard"}
                and closure is not None
                and not closure.terminal_closure
            ):
                return status(
                    "incomplete",
                    "audit_complete_but_terminal_closure_open",
                    str(matching_audit.audit_id),
                    degraded=True,
                )
            if (
                matching_audit.status == "complete_audited"
                and all_covered
                and not matching_audit.open_finding_ids
                and not matching_audit.open_obligation_ids
                and bool(getattr(matching_audit, "coverage_complete", True))
            ):
                return status(
                    "complete_audited",
                    "version_matched_audit_complete",
                    str(matching_audit.audit_id),
                    assurance_level="audited",
                    terminal_closure=True,
                )
            if (
                matching_audit.status == "complete_hard"
                and decision.status == "complete_hard"
                and not matching_audit.open_finding_ids
                and not matching_audit.open_obligation_ids
                and bool(getattr(matching_audit, "coverage_complete", True))
            ):
                return status(
                    "complete_hard",
                    "hard_evidence_and_audit_complete",
                    str(matching_audit.audit_id),
                    assurance_level="tool_supported",
                    terminal_closure=True,
                )
            return status(
                "incomplete",
                "final_audit_not_complete",
                str(matching_audit.audit_id),
                degraded=True,
            )

        if closure is not None and closure.completion_status == "complete_audited":
            return status(
                "complete_audited",
                "verification_closure_audited",
                closure.audit_id,
            )
        if closure is not None and closure.completion_status == "complete_hard" and closure.terminal_closure:
            return status(
                "complete_hard",
                "verification_closure_terminal",
                closure.audit_id,
            )
        if repaired:
            return status(
                "incomplete",
                "repaired_candidate_requires_final_audit",
                degraded=True,
            )
        if decision.status == "complete_hard":
            return status(
                "complete_hard",
                "all_required_obligations_have_hard_evidence",
            )
        return status(
            "incomplete",
            "audit_unavailable_or_obligations_unresolved",
            degraded=True,
        )

    @staticmethod
    def _proof_shape_complete(
        candidate: Any,
        response_mode: str,
        closure: VerificationClosure | None = None,
    ) -> bool:
        if str(response_mode) != "proof_full":
            return bool(str(candidate.final_answer).strip())
        # Prefer the shared semantic closure when available; merely repeating
        # an answer twice is not a proof.
        if closure is not None and closure.derivation_quality == "complete":
            return bool(str(candidate.final_answer).strip())
        steps = [
            str(item).strip()
            for item in getattr(candidate, "public_solution_steps", ())
            if str(item).strip()
        ]
        if len(steps) < 2:
            return False
        answer = " ".join(str(candidate.final_answer).split()).casefold()
        return bool(str(candidate.final_answer).strip()) and any(
            " ".join(step.split()).casefold() != answer
            for step in steps
        )
