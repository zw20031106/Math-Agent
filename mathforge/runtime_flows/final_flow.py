from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from mathforge.verification.completion import CompletionDecision


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
    ) -> FinalProofStatus:
        candidate_id = str(candidate.candidate_id)

        def status(
            value: str,
            reason: str,
            audit_id: str = "",
            degraded: bool = False,
        ) -> FinalProofStatus:
            return FinalProofStatus(
                candidate_id,
                value,
                reason,
                audit_id,
                degraded,
                decision.assurance_level,
                decision.terminal_closure,
            )

        if decision.status == "failed":
            return status("failed", "hard_evidence_failed")
        if not self._proof_shape_complete(candidate, response_mode):
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
        if matching_audit is not None:
            if matching_audit.status == "failed":
                return status(
                    "failed",
                    "final_audit_failed",
                    str(matching_audit.audit_id),
                )
            if (
                matching_audit.status == "complete_audited"
                and all_covered
                and not matching_audit.open_finding_ids
                and not matching_audit.open_obligation_ids
            ):
                return status(
                    "complete_audited",
                    "version_matched_audit_complete",
                    str(matching_audit.audit_id),
                )
            if (
                matching_audit.status == "complete_hard"
                and decision.status == "complete_hard"
                and not matching_audit.open_finding_ids
                and not matching_audit.open_obligation_ids
            ):
                return status(
                    "complete_hard",
                    "hard_evidence_and_audit_complete",
                    str(matching_audit.audit_id),
                )
            return status(
                "incomplete",
                "final_audit_not_complete",
                str(matching_audit.audit_id),
                degraded=True,
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
    def _proof_shape_complete(candidate: Any, response_mode: str) -> bool:
        if str(response_mode) != "proof_full":
            return bool(str(candidate.final_answer).strip())
        steps = [
            str(item).strip()
            for item in getattr(candidate, "public_solution_steps", ())
            if str(item).strip()
        ]
        return bool(str(candidate.final_answer).strip()) and len(steps) >= 2
