from __future__ import annotations

import re

from mathforge.harness.schemas import CandidateSolution, ProblemIR


class AnswerValidator:
    def validate(self, candidate: CandidateSolution, problem: ProblemIR) -> list[str]:
        answer = candidate.final_answer.strip()
        errors: list[str] = []
        if not answer:
            errors.append("empty_answer")
        elif problem.answer_type == "choice" and not re.fullmatch(r"[A-H](?:\s*[,、]\s*[A-H])*", answer, re.I):
            errors.append("invalid_choice")
        elif problem.answer_type == "integer" and not re.fullmatch(r"[+-]?\d+", answer):
            errors.append("invalid_integer")
        elif problem.answer_type == "fraction" and not (
            re.fullmatch(r"[+-]?\d+\s*/\s*\d+", answer)
            or re.fullmatch(r"\\frac\{[+-]?\d+\}\{\d+\}", answer)
        ):
            errors.append("invalid_fraction")
        return errors
