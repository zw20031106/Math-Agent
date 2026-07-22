from __future__ import annotations

from dataclasses import dataclass

from mathforge.harness.budget import CallBudget
from mathforge.harness.provider import OfficialClientProvider
from mathforge.harness.schemas import CandidateSolution, ProblemIR, RoutePlan
from mathforge.parsing.solution_parser import SolutionParser


_OUTPUT_INSTRUCTION = """Return a CandidateSolution JSON object when possible, with
method, solution_text, final_answer, answer_type, assumptions, theorems, claims,
and unresolved_obligations. Keep the exact final answer explicit."""


@dataclass(frozen=True)
class SolverRequest:
    candidate_id: str
    problem: ProblemIR
    route: RoutePlan
    skill_context: str
    primary_method_label: str
    forbidden_methods: tuple[str, ...] = ()


class PrimarySolver:
    role = "PrimarySolver"

    def build_messages(self, request: SolverRequest) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "You are PrimarySolver. Produce a rigorous, standard, independently "
                    f"verifiable solution. {_OUTPUT_INSTRUCTION}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Problem:\n{request.problem.normalized_problem}\n\nProvide a complete solution.\n\n"
                    f"Planned method family: {request.primary_method_label}.\n"
                    f"{request.skill_context}"
                ),
            },
        ]


class AlternativeSolver:
    role = "AlternativeSolver"

    def build_messages(self, request: SolverRequest) -> list[dict[str, str]]:
        forbidden = ", ".join(request.forbidden_methods) or request.primary_method_label
        return [
            {
                "role": "system",
                "content": (
                    "You are AlternativeSolver. Solve independently using a different core "
                    "method. You have not been given the PrimarySolver derivation. "
                    f"{_OUTPUT_INSTRUCTION}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Problem:\n{request.problem.normalized_problem}\n\nProvide a complete solution.\n\n"
                    f"Primary method label only: {request.primary_method_label}.\n"
                    f"Forbidden methods: {forbidden}.\n{request.skill_context}"
                ),
            },
        ]


class SolverExecutor:
    def __init__(self, provider: OfficialClientProvider, parser: SolutionParser) -> None:
        self._provider = provider
        self._parser = parser

    def execute(
        self,
        solver: PrimarySolver | AlternativeSolver,
        request: SolverRequest,
        budget: CallBudget,
        *,
        temperature: float,
        max_tokens: int,
    ) -> CandidateSolution:
        budget.consume()
        response = self._provider.chat(
            messages=solver.build_messages(request),
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if not response.strip():
            raise ValueError("empty solver response")
        budget.record_tokens(max(1, len(response) // 4))
        return self._parser.parse(
            response,
            candidate_id=request.candidate_id,
            role=solver.role,
            answer_type=request.problem.answer_type,
        )
