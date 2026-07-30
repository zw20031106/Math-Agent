from __future__ import annotations

from dataclasses import asdict, dataclass, field

from mathforge.harness.schemas import CandidateSolution, ProblemIR
from mathforge.output.answer_validator import AnswerValidator
from mathforge.verification.methods import method_contract_valid


class CandidateAdmissionError(ValueError):
    pass


@dataclass(frozen=True)
class CandidateAdmissionDecision:
    candidate_id: str
    accepted: bool
    rejection_codes: list[str]
    warning_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class CandidateAdmissionGate:
    """Apply the deterministic Candidate contract before evidence or arbitration."""

    def __init__(self, answer_validator: AnswerValidator | None = None) -> None:
        self._answer_validator = answer_validator or AnswerValidator()

    def evaluate(
        self,
        candidate: CandidateSolution,
        problem: ProblemIR,
        *,
        answer_shape_status: str | None = None,
    ) -> CandidateAdmissionDecision:
        rejection_codes: list[str] = []
        warning_codes: list[str] = []
        answer_type_is_hard = problem.answer_type_confidence >= 0.85
        try:
            candidate.validate()
        except (TypeError, ValueError):
            rejection_codes.append("candidate_schema_invalid")
        if (
            not method_contract_valid(candidate)
            and any(
                deviation.startswith("method_steps")
                for deviation in candidate.contract_deviations
            )
        ):
            rejection_codes.append("candidate_method_contract_invalid")
        if candidate.answer_type != problem.answer_type:
            if answer_type_is_hard:
                rejection_codes.append("incompatible_answer_type")
            else:
                warning_codes.extend(
                    [
                        "low_confidence_answer_type_soft_gate",
                        f"normalization_recovery:{candidate.answer_type}",
                    ]
                )
        if (
            candidate.parse_tier == "answer_recovered"
            and answer_shape_status is not None
            and answer_shape_status != "pass"
        ):
            rejection_codes.append("answer_recovery_evidence_gate_failed")
        answer_errors = self._answer_validator.validate(candidate, problem)
        if answer_type_is_hard:
            rejection_codes.extend(answer_errors)
        else:
            for error in answer_errors:
                if error == "empty_answer":
                    rejection_codes.append(error)
                else:
                    warning_codes.append(
                        f"soft_{error}"
                    )
        if (
            answer_shape_status is not None
            and answer_shape_status != "pass"
        ):
            target = (
                rejection_codes
                if answer_type_is_hard
                else warning_codes
            )
            target.append(f"answer_shape_{answer_shape_status}")
        rejection_codes = sorted(set(rejection_codes))
        warning_codes = sorted(set(warning_codes))
        return CandidateAdmissionDecision(
            candidate_id=candidate.candidate_id,
            accepted=not rejection_codes,
            rejection_codes=rejection_codes,
            warning_codes=warning_codes,
        )
