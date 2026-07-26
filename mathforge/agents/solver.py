from __future__ import annotations

from dataclasses import dataclass

from mathforge.agents.prompt_compiler import PromptCompilation, PromptCompiler
from mathforge.agents.registry import PromptContractLoader
from mathforge.context.snapshots import RoleContextView
from mathforge.harness.budget import CallBudget
from mathforge.harness.errors import BudgetExceeded, ModelResponseError
from mathforge.harness.provider import OfficialClientProvider
from mathforge.harness.schemas import CandidateSolution, ProblemIR, RoutePlan
from mathforge.parsing.solution_parser import (
    SolutionParser,
    candidate_response_validation,
)


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
        self._compiler = PromptCompiler(self._contracts)

    def build_messages(self, request: SolverRequest) -> list[dict[str, str]]:
        return self.compile_prompt(request).messages

    def compile_prompt(self, request: SolverRequest) -> PromptCompilation:
        context = (
            f"\nAuthorized context view:\n{request.context_view.to_prompt_json()}"
            if request.context_view is not None
            else ""
        )
        user = (
            f"Problem:\n{request.problem.normalized_problem}\n\n"
            f"Required core method family: {request.method_family}.\n"
            f"Forbidden method families: {', '.join(request.forbidden_method_families) or 'none'}.\n"
            f"{request.skill_context}{context}"
        )
        return self._compiler.compile_solver(
            "primary_solver",
            problem=request.problem,
            route=request.route,
            user_content=user,
            runtime_instructions=(
                "Produce a rigorous independently verifiable solution. "
                "Copy method exactly from the assigned method family."
            ),
        )


class AlternativeSolver:
    role = "AlternativeSolver"

    def __init__(self, contracts: PromptContractLoader | None = None) -> None:
        self._contracts = contracts or PromptContractLoader()
        self._compiler = PromptCompiler(self._contracts)

    def build_messages(self, request: SolverRequest) -> list[dict[str, str]]:
        return self.compile_prompt(request).messages

    def compile_prompt(self, request: SolverRequest) -> PromptCompilation:
        forbidden = ", ".join(request.forbidden_method_families) or "none"
        context = (
            f"\nAuthorized context view:\n{request.context_view.to_prompt_json()}"
            if request.context_view is not None
            else ""
        )
        user = (
            f"Problem:\n{request.problem.normalized_problem}\n\n"
            f"Required core method family: {request.method_family}.\n"
            f"Forbidden method families: {forbidden}.\n{request.skill_context}{context}"
        )
        return self._compiler.compile_solver(
            "alternative_solver",
            problem=request.problem,
            route=request.route,
            user_content=user,
            runtime_instructions=(
                "Solve independently using only the assigned core method family. "
                "Copy method exactly from the assigned method family."
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
        optional: bool = False,
    ) -> CandidateSolution:
        if request.candidate_id.startswith("lemma-round-"):
            stage = "lemma"
        elif solver.role == "PrimarySolver":
            stage = "primary"
        else:
            stage = "alternative"
        budget.consume(stage=stage, optional=optional)
        compilation = solver.compile_prompt(request)
        messages = compilation.messages
        budget.record_prompt_chars(
            sum(len(message["content"]) for message in messages)
        )
        response = self._provider.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=PromptCompiler.bounded_output_tokens(
                max_tokens,
                compilation.max_output_tokens,
            ),
            budget=budget,
            stage=stage,
        )
        if not response.strip():
            raise ValueError("empty solver response")
        if budget.deadline.must_finalize():
            raise BudgetExceeded("solver response arrived after finalize cutoff")
        budget.ensure_stage("solution_parser")
        candidate = self._parser.parse(
            response,
            candidate_id=request.candidate_id,
            role=solver.role,
            answer_type=request.problem.answer_type,
        )
        validation_code, rejected = candidate_response_validation(candidate)
        budget.record_model_response_validation(
            getattr(response, "model_call_index", None),
            validation_code,
            rejected=rejected,
        )
        if rejected:
            raise ModelResponseError(validation_code)
        candidate.planned_method_family = request.method_family
        if candidate.method.strip().lower() != request.method_family.strip().lower():
            candidate.parse_status = f"{candidate.parse_status}:method_contract_deviation"
            candidate.contract_deviations.append("method:planned_method_family")
        candidate.validate()
        return candidate
