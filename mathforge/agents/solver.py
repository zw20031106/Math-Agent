from __future__ import annotations

from dataclasses import dataclass

from mathforge.agents.registry import PromptContractLoader
from mathforge.context.snapshots import RoleContextView
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
    method_family: str
    forbidden_method_families: tuple[str, ...] = ()
    context_view: RoleContextView | None = None


class PrimarySolver:
    role = "PrimarySolver"

    def __init__(self, contracts: PromptContractLoader | None = None) -> None:
        self._contracts = contracts or PromptContractLoader()

    def build_messages(self, request: SolverRequest) -> list[dict[str, str]]:
        context = (
            f"\nAuthorized context view:\n{request.context_view.to_prompt_json()}"
            if request.context_view is not None
            else ""
        )
        user = (
            f"Problem:\n{request.problem.normalized_problem}\n\nProvide a complete solution.\n\n"
            f"Required core method family: {request.method_family}.\n"
            f"Forbidden method families: {', '.join(request.forbidden_method_families) or 'none'}.\n"
            f"{request.skill_context}{context}"
        )
        return self._contracts.messages(
            "primary_solver",
            user,
            (
                "Produce a rigorous independently verifiable solution. "
                f"{_OUTPUT_INSTRUCTION} Set method exactly to the assigned method family."
            ),
        )


class AlternativeSolver:
    role = "AlternativeSolver"

    def __init__(self, contracts: PromptContractLoader | None = None) -> None:
        self._contracts = contracts or PromptContractLoader()

    def build_messages(self, request: SolverRequest) -> list[dict[str, str]]:
        forbidden = ", ".join(request.forbidden_method_families) or "none"
        context = (
            f"\nAuthorized context view:\n{request.context_view.to_prompt_json()}"
            if request.context_view is not None
            else ""
        )
        user = (
            f"Problem:\n{request.problem.normalized_problem}\n\nProvide a complete solution.\n\n"
            f"Required core method family: {request.method_family}.\n"
            f"Forbidden method families: {forbidden}.\n{request.skill_context}{context}"
        )
        return self._contracts.messages(
            "alternative_solver",
            user,
            (
                "Solve independently using only the assigned core method family. "
                f"{_OUTPUT_INSTRUCTION} Set method exactly to the assigned method family."
            ),
        )


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
        candidate = self._parser.parse(
            response,
            candidate_id=request.candidate_id,
            role=solver.role,
            answer_type=request.problem.answer_type,
        )
        candidate.planned_method_family = request.method_family
        if candidate.method.strip().lower() != request.method_family.strip().lower():
            candidate.parse_status = f"{candidate.parse_status}:method_contract_deviation"
        return candidate
