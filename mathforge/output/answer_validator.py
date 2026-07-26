from __future__ import annotations

from mathforge.harness.schemas import CandidateSolution, ProblemIR
from mathforge.verification.answer_normalization import answer_shape_valid


class AnswerValidator:
    def validate(self, candidate: CandidateSolution, problem: ProblemIR) -> list[str]:
        answer = candidate.final_answer.strip()
        errors: list[str] = []
        if not answer:
            errors.append("empty_answer")
        elif not answer_shape_valid(answer, problem.answer_type):
            errors.append(f"invalid_{problem.answer_type}")
        return errors
