from __future__ import annotations

import re

from mathforge.harness.schemas import CandidateSolution, ProblemIR


_ANSWER_BLOCK = re.compile(
    r"^\s*(?:(?:final\s*)?answer|最终答案|答案)\s*[:：].*$",
    re.IGNORECASE | re.MULTILINE,
)


class DeterministicFormatter:
    def format(self, candidate: CandidateSolution, problem: ProblemIR) -> str:
        del problem
        answer = candidate.final_answer.strip()
        solution = candidate.solution_text.strip()
        if not solution:
            return answer
        if candidate.parse_status.split(":", 1)[0] == "raw_text":
            return solution
        without_answer_blocks = _ANSWER_BLOCK.sub("", solution).strip()
        if not answer:
            return without_answer_blocks
        if without_answer_blocks:
            return f"{without_answer_blocks}\n\nFinal answer: {answer}"
        return f"Final answer: {answer}"
