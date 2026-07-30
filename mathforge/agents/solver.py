from __future__ import annotations

from dataclasses import dataclass
import json

from mathforge.agents.prompt_compiler import PromptCompilation, PromptCompiler
from mathforge.agents.registry import PromptContractLoader
from mathforge.context.snapshots import RoleContextView
from mathforge.harness.budget import CallBudget
from mathforge.harness.errors import (
    BudgetExceeded,
    ModelResponseError,
    ModelTransportError,
)
from mathforge.harness.provider import OfficialClientProvider
from mathforge.harness.reasoning_state import (
    ProgressDeltaParser,
    RoundDelta,
)
from mathforge.harness.schemas import (
    CandidateSolution,
    ProblemIR,
    RoutePlan,
    SchemaValidationError,
)
from mathforge.harness.transport import RETRYABLE_TRANSPORT_FAILURE_CODES
from mathforge.parsing.solution_parser import (
    SolutionParser,
    candidate_response_validation,
)

_PRIMARY_CONTRACT_ATTEMPTS = 2


@dataclass(frozen=True)
class SolverRequest:
    candidate_id: str
    problem: ProblemIR
    route: RoutePlan
    skill_context: str
    method_family: str
    forbidden_method_families: tuple[str, ...] = ()
    context_view: RoleContextView | None = None
    reasoning_state_json: str = ""


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
            f"{_problem_structure_prompt(request.problem)}\n"
            f"{request.skill_context}{context}"
            f"{_reasoning_state_prompt(request.reasoning_state_json)}"
        )
        return self._compiler.compile_solver(
            "primary_solver",
            problem=request.problem,
            route=request.route,
            user_content=user,
            runtime_instructions=(
                "Public protocol mode is synthesize. Produce a rigorous "
                "independently verifiable solution. "
                "State the method concisely; the Host treats its wording as a "
                "diversity signal. When a public ReasoningState is supplied, "
                "synthesize from it, preserve its ProblemFrame and Claim "
                "dependencies, and list any still-open obligation."
            ),
        )

    def compile_progress_prompt(
        self,
        request: SolverRequest,
        *,
        mode: str,
    ) -> PromptCompilation:
        context = (
            f"\nAuthorized context view:\n{request.context_view.to_prompt_json()}"
            if request.context_view is not None
            else ""
        )
        user = (
            f"Problem:\n{request.problem.normalized_problem}\n\n"
            f"Required core method family: {request.method_family}.\n"
            f"{_problem_structure_prompt(request.problem)}\n"
            f"{request.skill_context}{context}"
            f"{_reasoning_state_prompt(request.reasoning_state_json)}"
        )
        return self._compiler.compile_solver_progress(
            "primary_solver",
            problem=request.problem,
            route=request.route,
            user_content=user,
            mode=mode,
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
            f"Forbidden method families: {forbidden}.\n"
            f"{_problem_structure_prompt(request.problem)}\n"
            f"{request.skill_context}{context}"
        )
        return self._compiler.compile_solver(
            "alternative_solver",
            problem=request.problem,
            route=request.route,
            user_content=user,
            runtime_instructions=(
                "Public protocol mode is synthesize. Solve independently using "
                "only the assigned core method family. "
                "State the method concisely; the Host treats its wording as a "
                "diversity signal."
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
        compilation = solver.compile_prompt(request)
        messages = compilation.messages
        max_attempts = (
            _PRIMARY_CONTRACT_ATTEMPTS
            if solver.role == "PrimarySolver"
            else 1
        )
        last_response_error: ModelResponseError | None = None
        last_transport_error: ModelTransportError | None = None
        retry_details: tuple[str, ...] = ()
        for attempt in range(max_attempts):
            try:
                budget.consume(
                    stage=stage,
                    optional=optional or attempt > 0,
                )
            except BudgetExceeded:
                if last_response_error is not None:
                    raise last_response_error
                if last_transport_error is not None:
                    raise last_transport_error
                raise
            attempt_messages = (
                messages
                if attempt == 0 or last_response_error is None
                else [
                    *messages,
                    {
                        "role": "user",
                        "content": _candidate_contract_retry_feedback(
                            retry_details
                        ),
                    },
                ]
            )
            budget.record_prompt_chars(
                sum(len(message["content"]) for message in attempt_messages)
            )
            try:
                response = self._provider.chat(
                    messages=attempt_messages,
                    temperature=(
                        temperature
                        if attempt == 0 or last_response_error is None
                        else 0.0
                    ),
                    max_tokens=PromptCompiler.bounded_output_tokens(
                        max_tokens,
                        compilation.max_output_tokens,
                    ),
                    budget=budget,
                    stage=stage,
                )
            except ModelTransportError as error:
                if last_response_error is not None:
                    transport_code = getattr(
                        error,
                        "code",
                        "retry_provider_failure",
                    )
                    raise ModelResponseError(
                        last_response_error.code,
                        details=(
                            *last_response_error.details,
                            f"retry_transport:{transport_code}",
                        ),
                    ) from error
                if (
                    solver.role == "PrimarySolver"
                    and attempt + 1 < max_attempts
                    and error.code in RETRYABLE_TRANSPORT_FAILURE_CODES
                ):
                    last_transport_error = error
                    continue
                raise
            budget.ensure_stage("solution_parser")
            try:
                candidate = self._parser.parse(
                    response,
                    candidate_id=request.candidate_id,
                    role=solver.role,
                    answer_type=request.problem.answer_type,
                )
            except SchemaValidationError:
                validation_code = "candidate_schema_invalid"
                retry_details = ("nested_schema_invariant:invalid",)
                budget.record_model_response_validation(
                    getattr(response, "model_call_index", None),
                    validation_code,
                    rejected=True,
                )
                last_response_error = ModelResponseError(
                    validation_code,
                    details=retry_details,
                )
                continue
            validation_code, rejected = candidate_response_validation(candidate)
            if (
                not rejected
                and candidate.method.strip().lower()
                != request.method_family.strip().lower()
            ):
                candidate.parse_status = (
                    f"{candidate.parse_status}:method_contract_deviation"
                )
                candidate.contract_deviations.append(
                    "method:planned_method_family"
                )
                validation_code = "candidate_method_deviation"
            budget.record_model_response_validation(
                getattr(response, "model_call_index", None),
                validation_code,
                rejected=rejected,
            )
            if not rejected:
                break
            last_transport_error = None
            retry_details = _candidate_validation_details(candidate)
            last_response_error = ModelResponseError(
                validation_code,
                details=retry_details,
            )
        else:
            if last_response_error is not None:
                raise last_response_error
            if last_transport_error is not None:
                raise last_transport_error
            raise RuntimeError("unreachable candidate response state")
        candidate.planned_method_family = request.method_family
        candidate.validate()
        return candidate

    def execute_progress(
        self,
        solver: PrimarySolver,
        request: SolverRequest,
        budget: CallBudget,
        *,
        mode: str,
        temperature: float,
        max_tokens: int,
        optional: bool,
    ) -> RoundDelta:
        compilation = solver.compile_progress_prompt(request, mode=mode)
        budget.consume(stage="primary", optional=optional)
        budget.record_prompt_chars(
            sum(len(message["content"]) for message in compilation.messages)
        )
        response = self._provider.chat(
            messages=compilation.messages,
            temperature=temperature,
            max_tokens=PromptCompiler.bounded_output_tokens(
                max_tokens,
                compilation.max_output_tokens,
            ),
            budget=budget,
            stage="primary",
        )
        try:
            delta = ProgressDeltaParser().parse(
                response,
                round_index=_reasoning_state_version(
                    request.reasoning_state_json
                ),
                mode=mode,
            )
        except (ValueError, TypeError) as error:
            budget.record_model_response_validation(
                getattr(response, "model_call_index", None),
                "progress_delta_invalid",
                rejected=True,
            )
            raise ModelResponseError("progress_delta_invalid") from error
        budget.record_model_response_validation(
            getattr(response, "model_call_index", None),
            "progress_delta_valid",
            rejected=False,
        )
        return delta


def _problem_structure_prompt(problem: ProblemIR) -> str:
    fields = (
        ("Target kind", [problem.target_kind]),
        ("Definitions", problem.definitions),
        ("Quantifiers", problem.quantifiers),
        ("Constraints", problem.constraints),
        ("Ambiguities", problem.ambiguities),
        ("Structural difficulty", problem.difficulty_features),
        ("Suggested decomposition", problem.subproblem_hints),
    )
    lines = ["Host-parsed public problem structure:"]
    for label, values in fields:
        bounded = [
            str(value).strip()[:240]
            for value in values
            if str(value).strip()
        ]
        if bounded:
            lines.append(f"- {label}: {'; '.join(bounded)}")
    return "\n".join(lines)


def _reasoning_state_prompt(state_json: str) -> str:
    if not state_json.strip():
        return ""
    return (
        "\nPublic ReasoningState JSON (the only cross-round mathematical "
        f"state):\n{state_json}"
    )


def _reasoning_state_version(state_json: str) -> int:
    try:
        value = json.loads(state_json)
        version = value.get("version")
    except (AttributeError, TypeError, ValueError):
        version = None
    if type(version) is not int or version < 1:
        raise ModelResponseError("reasoning_state_version_invalid")
    return version


def _candidate_validation_details(
    candidate: CandidateSolution,
) -> tuple[str, ...]:
    details = [f"parse_status:{candidate.parse_status}"]
    details.extend(candidate.contract_deviations)
    return tuple(dict.fromkeys(details))[:32]


def _candidate_contract_retry_feedback(details: tuple[str, ...]) -> str:
    feedback = ", ".join(details) if details else "candidate_contract_invalid"
    return (
        "The previous Candidate was rejected by the Host contract. Regenerate it "
        "from scratch as one bare strict JSON object using the exact structural "
        "shape and exact nested key names in the system message. Do not add a "
        f"Markdown fence, aliases, or extra fields. Validation codes: {feedback}."
    )
