from __future__ import annotations

from mathforge.harness.schemas import CandidateSolution, ProblemIR


class DeterministicFormatter:
    def format(self, candidate: CandidateSolution, problem: ProblemIR) -> str:
        del problem
        answer = candidate.final_answer.strip()
        solution = candidate.solution_text.strip()
        if not solution:
            return answer
        if candidate.parse_status == "raw_text" or answer == solution:
            return solution
        if answer and answer not in solution:
            return f"{solution}\n\nFinal answer: {answer}"
        return solution
