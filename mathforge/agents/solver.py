from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json

from mathforge.agent_runtime.protocol import (
    AgentTurnPayload,
    AgentTurnPayloadParser,
    ParsedAgentTurn,
    PROTOCOL_SCHEMA_VERSION,
)
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
_TRUNCATION_RETRY_MAX_TOKENS = 2048


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

    def compile_prompt(
        self,
        request: SolverRequest,
        *,
        autonomous: bool = False,
        compact: bool = False,
    ) -> PromptCompilation:
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
            autonomous=autonomous,
            compact=compact,
        )

    def compile_progress_prompt(
        self,
        request: SolverRequest,
        *,
        mode: str,
        autonomous: bool = False,
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
            autonomous=autonomous,
        )

    def compile_emergency_prompt(
        self,
        request: SolverRequest,
    ) -> PromptCompilation:
        return self._compiler.compile_emergency_answer(
            problem=request.problem,
            user_content=(
                f"Problem:\n{request.problem.normalized_problem}\n\n"
                "Return the exact answer and one compact mathematical check."
            ),
        )


class AlternativeSolver:
    role = "AlternativeSolver"

    def __init__(self, contracts: PromptContractLoader | None = None) -> None:
        self._contracts = contracts or PromptContractLoader()
        self._compiler = PromptCompiler(self._contracts)

    def build_messages(self, request: SolverRequest) -> list[dict[str, str]]:
        return self.compile_prompt(request).messages

    def compile_prompt(
        self,
        request: SolverRequest,
        *,
        autonomous: bool = False,
        compact: bool = False,
    ) -> PromptCompilation:
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
            f"{_reasoning_state_prompt(request.reasoning_state_json)}"
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
            autonomous=autonomous,
            compact=compact,
        )

    def compile_progress_prompt(
        self,
        request: SolverRequest,
        *,
        mode: str,
        autonomous: bool = False,
    ) -> PromptCompilation:
        context = (
            f"\nAuthorized context view:\n{request.context_view.to_prompt_json()}"
            if request.context_view is not None
            else ""
        )
        user = (
            f"Problem:\n{request.problem.normalized_problem}\n\n"
            f"Required core method family: {request.method_family}.\n"
            f"Forbidden method families: "
            f"{', '.join(request.forbidden_method_families) or 'none'}.\n"
            f"{_problem_structure_prompt(request.problem)}\n"
            f"{request.skill_context}{context}"
            f"{_reasoning_state_prompt(request.reasoning_state_json)}"
        )
        return self._compiler.compile_solver_progress(
            "alternative_solver",
            problem=request.problem,
            route=request.route,
            user_content=user,
            mode=mode,
            runtime_instructions=(
                "Advance only the isolated Alternative state. Do not infer or "
                "request the Primary candidate before publishing your own."
            ),
            autonomous=autonomous,
        )


@dataclass(frozen=True)
class AutonomousSolverTurn:
    parsed: ParsedAgentTurn
    delta: RoundDelta | None = None
    candidate: CandidateSolution | None = None

    @property
    def action(self) -> str:
        return self.parsed.payload.action

    @property
    def partial(self) -> bool:
        return self.parsed.partial


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
        compact: bool = False,
    ) -> CandidateSolution:
        if request.candidate_id.startswith("lemma-round-"):
            stage = "lemma"
        elif solver.role == "PrimarySolver":
            stage = "primary"
        else:
            stage = "alternative"
        compilation = solver.compile_prompt(request, compact=compact)
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
                turn_kind = (
                    "lemma_curator"
                    if stage == "lemma"
                    else (
                        "solver_candidate_proof"
                        if request.problem.response_mode == "proof_full"
                        else "solver_candidate_standard"
                    )
                )
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
                    turn_kind=turn_kind,
                    agent_id=f"{solver.role}:{request.candidate_id}",
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
                    planned_method_family=request.method_family,
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
            budget.record_model_protocol_telemetry(
                getattr(response, "model_call_index", None),
                candidate.parse_status,
                assurance_degradation=(
                    "none" if candidate.parse_tier == "strict" else "medium"
                ),
                candidate_parse_tier=candidate.parse_tier,
            )
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

    def execute_emergency_answer(
        self,
        solver: PrimarySolver,
        request: SolverRequest,
        budget: CallBudget,
        *,
        max_tokens: int,
    ) -> CandidateSolution:
        compilation = solver.compile_emergency_prompt(request)
        budget.consume(
            stage="primary",
            optional=False,
            action_category="candidate_completion",
        )
        budget.record_prompt_chars(
            sum(len(message["content"]) for message in compilation.messages)
        )
        response = self._provider.chat(
            messages=compilation.messages,
            temperature=0.0,
            max_tokens=PromptCompiler.bounded_output_tokens(
                max_tokens,
                compilation.max_output_tokens,
            ),
            budget=budget,
            stage="primary",
            turn_kind="solver_compact_synthesis",
            agent_id=f"{solver.role}:{request.candidate_id}",
        )
        candidate = self._parser.parse(
            response,
            candidate_id=request.candidate_id,
            role=solver.role,
            answer_type=request.problem.answer_type,
            planned_method_family=request.method_family,
        )
        validation_code, rejected = candidate_response_validation(candidate)
        budget.record_model_protocol_telemetry(
            getattr(response, "model_call_index", None),
            candidate.parse_status,
            assurance_degradation=(
                "none" if candidate.parse_tier == "strict" else "medium"
            ),
            candidate_parse_tier=candidate.parse_tier,
        )
        budget.record_model_response_validation(
            getattr(response, "model_call_index", None),
            validation_code,
            rejected=rejected,
        )
        if rejected:
            raise ModelResponseError(validation_code)
        candidate.parse_status = f"{candidate.parse_status}:emergency_direct"
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
        budget.consume(
            stage="primary",
            optional=optional,
            action_category="speculative_exploration",
        )
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
            turn_kind="solver_progress",
            agent_id="PrimarySolver",
        )
        try:
            delta = ProgressDeltaParser().parse(
                response,
                round_index=_reasoning_state_version(
                    request.reasoning_state_json
                ),
                mode=mode,
                branch_id=f"branch-{request.candidate_id}",
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

    def execute_autonomous_progress(
        self,
        solver: PrimarySolver | AlternativeSolver,
        request: SolverRequest,
        budget: CallBudget,
        *,
        mode: str,
        temperature: float,
        max_tokens: int,
        optional: bool,
    ) -> AutonomousSolverTurn:
        compilation = solver.compile_progress_prompt(
            request,
            mode=mode,
            autonomous=True,
        )
        stage = "primary" if solver.role == "PrimarySolver" else "alternative"
        budget.consume(
            stage=stage,
            optional=optional,
            action_category="speculative_exploration",
        )
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
            stage=stage,
            turn_kind="solver_progress",
            agent_id=f"{solver.role}:{request.candidate_id}",
            agent_action_protocol=True,
        )
        parsed = self._parse_agent_turn(
            response,
            budget,
            allowed_actions=(
                "continue_reasoning",
                "request_lemma",
                "request_tool_check",
                "request_replan",
                "complete",
                "abstain",
            ),
            truncated=_response_was_truncated(response),
            truncation_reason=_response_truncation_reason(response),
        )
        if parsed.payload.task_result_type not in {
            "ProgressArtifact",
            "ToolRequestArtifact",
            "CheckpointArtifact",
        }:
            self._fail_agent_turn(response, budget, "agent_turn_result_type_invalid")
            raise ModelResponseError("agent_turn_result_type_invalid")
        delta = None
        if parsed.payload.public_state_delta:
            try:
                delta = ProgressDeltaParser().parse(
                    json.dumps(
                        parsed.payload.public_state_delta,
                        ensure_ascii=False,
                    ),
                    round_index=_reasoning_state_version(
                        request.reasoning_state_json
                    ),
                    mode=mode,
                    branch_id=f"branch-{request.candidate_id}",
                )
            except (ValueError, TypeError) as error:
                self._fail_agent_turn(response, budget, "agent_progress_delta_invalid")
                budget.record_model_response_validation(
                    getattr(response, "model_call_index", None),
                    "agent_progress_delta_invalid",
                    rejected=True,
                )
                raise ModelResponseError("agent_progress_delta_invalid") from error
        if parsed.payload.action != "abstain" and delta is None:
            self._fail_agent_turn(response, budget, "agent_progress_delta_missing")
            raise ModelResponseError("agent_progress_delta_missing")
        budget.record_model_response_validation(
            getattr(response, "model_call_index", None),
            (
                "agent_progress_partial"
                if parsed.partial
                else "agent_progress_valid"
            ),
            rejected=False,
        )
        self._complete_agent_turn(response, budget)
        return AutonomousSolverTurn(parsed=parsed, delta=delta)

    def execute_autonomous_candidate(
        self,
        solver: PrimarySolver | AlternativeSolver,
        request: SolverRequest,
        budget: CallBudget,
        *,
        temperature: float,
        max_tokens: int,
        compact: bool = False,
        input_artifact_ids: tuple[str, ...] = (),
    ) -> AutonomousSolverTurn:
        compilation = solver.compile_prompt(
            request,
            autonomous=True,
            compact=compact,
        )
        stage = "primary" if solver.role == "PrimarySolver" else "alternative"
        turn_kind = (
            "solver_compact_synthesis"
            if compact
            else (
                "solver_candidate_proof"
                if request.problem.response_mode == "proof_full"
                else "solver_candidate_standard"
            )
        )
        budget.consume(
            stage=stage,
            optional=False,
            action_category="candidate_completion",
        )
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
            stage=stage,
            turn_kind=turn_kind,
            agent_id=f"{solver.role}:{request.candidate_id}",
            agent_action_protocol=True,
            input_artifact_ids=input_artifact_ids,
        )
        if _response_was_truncated(response):
            salvaged = self._parser.recover_answer_candidate(
                response,
                candidate_id=request.candidate_id,
                role=solver.role,
                answer_type=request.problem.answer_type,
                planned_method_family=request.method_family,
            )
            if salvaged is not None:
                return self._recovered_autonomous_candidate(
                    response,
                    salvaged,
                    budget,
                    recovery_reason="answer_salvaged_from_truncated_response",
                )
            self._fail_agent_turn(response, budget, "response_truncated_retry")
            response = self._retry_truncated_answer(
                solver,
                request,
                budget,
                stage=stage,
                input_artifact_ids=input_artifact_ids,
            )
        try:
            parsed = self._parse_agent_turn(
                response,
                budget,
                allowed_actions=("publish_candidate", "abstain"),
                truncated=_response_was_truncated(response),
                truncation_reason=_response_truncation_reason(response),
            )
        except ModelResponseError:
            candidate = self._parser.recover_answer_candidate(
                response,
                candidate_id=request.candidate_id,
                role=solver.role,
                answer_type=request.problem.answer_type,
                planned_method_family=request.method_family,
            )
            if candidate is None:
                raise
            return self._recovered_autonomous_candidate(
                response,
                candidate,
                budget,
                recovery_reason="complete_answer_from_damaged_agent_turn",
            )
        if parsed.payload.action == "abstain":
            if parsed.payload.task_result_type != "CheckpointArtifact":
                self._fail_agent_turn(response, budget, "agent_turn_result_type_invalid")
                raise ModelResponseError("agent_turn_result_type_invalid")
            self._complete_agent_turn(response, budget)
            return AutonomousSolverTurn(parsed=parsed)
        if parsed.payload.task_result_type != "CandidateArtifact":
            self._fail_agent_turn(response, budget, "agent_turn_result_type_invalid")
            raise ModelResponseError("agent_turn_result_type_invalid")
        try:
            candidate = self._parser.parse(
                json.dumps(parsed.payload.result_payload, ensure_ascii=False),
                candidate_id=request.candidate_id,
                role=solver.role,
                answer_type=request.problem.answer_type,
                planned_method_family=request.method_family,
            )
        except SchemaValidationError as error:
            self._fail_agent_turn(response, budget, "candidate_schema_invalid")
            budget.record_model_response_validation(
                getattr(response, "model_call_index", None),
                "candidate_schema_invalid",
                rejected=True,
            )
            raise ModelResponseError("candidate_schema_invalid") from error
        validation_code, rejected = candidate_response_validation(candidate)
        budget.record_model_protocol_telemetry(
            getattr(response, "model_call_index", None),
            parsed.parse_tier,
            parsed.recovery_reason,
            parsed.assurance_degradation,
            candidate_parse_tier=candidate.parse_tier,
        )
        if rejected:
            self._fail_agent_turn(response, budget, validation_code)
            budget.record_model_response_validation(
                getattr(response, "model_call_index", None),
                validation_code,
                rejected=True,
            )
            raise ModelResponseError(
                validation_code,
                details=_candidate_validation_details(candidate),
            )
        if candidate.method.strip().lower() != request.method_family.strip().lower():
            candidate.parse_status = (
                f"{candidate.parse_status}:method_contract_deviation"
            )
            candidate.contract_deviations.append("method:planned_method_family")
            validation_code = "candidate_method_deviation"
        budget.record_model_response_validation(
            getattr(response, "model_call_index", None),
            validation_code,
            rejected=False,
        )
        candidate.planned_method_family = request.method_family
        candidate.validate()
        self._complete_agent_turn(response, budget)
        return AutonomousSolverTurn(parsed=parsed, candidate=candidate)

    def _retry_truncated_answer(
        self,
        solver: PrimarySolver | AlternativeSolver,
        request: SolverRequest,
        budget: CallBudget,
        *,
        stage: str,
        input_artifact_ids: tuple[str, ...],
    ) -> str:
        budget.record_model_retry("truncated_answer_only")
        budget.consume(
            stage=stage,
            optional=False,
            action_category="candidate_completion",
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "Solve the supplied problem. Output only the final answer as "
                    "\\boxed{answer}; do not include explanations or JSON."
                ),
            },
            {
                "role": "user",
                "content": request.problem.normalized_problem,
            },
        ]
        budget.record_prompt_chars(
            sum(len(message["content"]) for message in messages)
        )
        return self._provider.chat(
            messages=messages,
            temperature=0.0,
            max_tokens=_TRUNCATION_RETRY_MAX_TOKENS,
            budget=budget,
            stage=stage,
            turn_kind="solver_compact_synthesis",
            agent_id=f"{solver.role}:{request.candidate_id}:truncation-retry",
            agent_action_protocol=True,
            input_artifact_ids=input_artifact_ids,
        )

    def _recovered_autonomous_candidate(
        self,
        response: str,
        candidate: CandidateSolution,
        budget: CallBudget,
        *,
        recovery_reason: str,
    ) -> AutonomousSolverTurn:
        candidate.degraded = True
        if "truncation_recovery" not in candidate.contract_deviations:
            candidate.contract_deviations.append("truncation_recovery")
        payload = AgentTurnPayload(
            protocol_version=PROTOCOL_SCHEMA_VERSION,
            task_result_type="CandidateArtifact",
            action="publish_candidate",
            public_state_delta={},
            result_payload={
                "method": candidate.method,
                "final_answer": candidate.final_answer,
                "public_solution_steps": list(candidate.public_solution_steps),
                "claims": [],
                "solution_text": candidate.solution_text,
                "assumptions": [],
                "theorems": [],
                "unresolved_obligations": [],
            },
            outbound_intents=(),
            progress_summary="Recovered a public answer from a truncated response.",
            stop_reason="answer_salvaged",
        )
        parsed = ParsedAgentTurn(
            payload=payload,
            response_sha256=sha256(str(response).encode("utf-8")).hexdigest(),
            partial=_response_was_truncated(response),
            truncation_reason=_response_truncation_reason(response),
            parse_tier="semantic_answer_salvage",
            recovery_reason=recovery_reason,
            assurance_degradation="high",
        )
        budget.record_model_protocol_telemetry(
            getattr(response, "model_call_index", None),
            parsed.parse_tier,
            parsed.recovery_reason,
            parsed.assurance_degradation,
            candidate_parse_tier=candidate.parse_tier,
        )
        budget.record_model_response_validation(
            getattr(response, "model_call_index", None),
            "answer_recovered_candidate",
            rejected=False,
        )
        self._complete_recovered_agent_turn(response, budget, parsed)
        candidate.validate()
        return AutonomousSolverTurn(parsed=parsed, candidate=candidate)

    @staticmethod
    def _parse_agent_turn(
        response: str,
        budget: CallBudget,
        *,
        allowed_actions: tuple[str, ...],
        truncated: bool,
        truncation_reason: str,
    ) -> ParsedAgentTurn:
        try:
            parsed = AgentTurnPayloadParser().parse(
                response,
                allowed_actions=allowed_actions,
                truncated=truncated,
                truncation_reason=truncation_reason,
            )
            budget.record_model_protocol_telemetry(
                getattr(response, "model_call_index", None),
                parsed.parse_tier,
                parsed.recovery_reason,
                parsed.assurance_degradation,
            )
            return parsed
        except (TypeError, ValueError) as error:
            SolverExecutor._fail_agent_turn(
                response,
                budget,
                "agent_turn_payload_invalid",
            )
            raise ModelResponseError("agent_turn_payload_invalid") from error

    @staticmethod
    def _complete_agent_turn(response: str, budget: CallBudget) -> None:
        runtime = budget.agent_runtime
        turn_id = str(getattr(response, "protocol_turn_id", ""))
        if runtime is None or not turn_id:
            return
        try:
            lineage = runtime.complete_model_turn(
                turn_id,
                str(response),
                agent_action_protocol=True,
                response_truncated=_response_was_truncated(response),
                truncation_reason=_response_truncation_reason(response),
            )
        except Exception as error:
            runtime.fail_model_turn(turn_id, "agent_protocol_publish_failed")
            raise ModelResponseError("agent_protocol_publish_failed") from error
        call_index = getattr(response, "model_call_index", None)
        if call_index is not None:
            budget.record_model_call_lineage(call_index, lineage)

    @staticmethod
    def _complete_recovered_agent_turn(
        response: str,
        budget: CallBudget,
        parsed: ParsedAgentTurn,
    ) -> None:
        runtime = budget.agent_runtime
        turn_id = str(getattr(response, "protocol_turn_id", ""))
        if runtime is None or not turn_id:
            return
        synthetic = json.dumps(parsed.payload.to_dict(), ensure_ascii=False)
        lineage = runtime.complete_model_turn(
            turn_id,
            synthetic,
            agent_action_protocol=True,
            response_truncated=parsed.partial,
            truncation_reason=parsed.truncation_reason,
            recovery_metadata={
                "response_sha256": parsed.response_sha256,
                "parse_tier": parsed.parse_tier,
                "recovery_reason": parsed.recovery_reason,
                "assurance_degradation": parsed.assurance_degradation,
            },
        )
        call_index = getattr(response, "model_call_index", None)
        if call_index is not None:
            budget.record_model_call_lineage(call_index, lineage)

    @staticmethod
    def _fail_agent_turn(
        response: str,
        budget: CallBudget,
        failure_code: str,
    ) -> None:
        runtime = budget.agent_runtime
        turn_id = str(getattr(response, "protocol_turn_id", ""))
        if runtime is not None and turn_id:
            runtime.fail_model_turn(turn_id, failure_code)
        call_index = getattr(response, "model_call_index", None)
        if call_index is not None:
            budget.record_model_call_lineage(
                call_index,
                {
                    "turn_id": turn_id,
                    "agent_protocol_status": "domain_validation_failed",
                    "failure_code": failure_code,
                },
            )


def _problem_structure_prompt(problem: ProblemIR) -> str:
    fields = (
        ("Response mode", [problem.response_mode]),
        ("Answer type", [problem.answer_type]),
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


def _response_was_truncated(response: str) -> bool:
    return bool(
        getattr(response, "output_budget_exceeded", False)
        or str(getattr(response, "finish_reason", "")).casefold()
        in {"length", "length_inferred"}
    )


def _response_truncation_reason(response: str) -> str:
    finish_reason = str(getattr(response, "finish_reason", "")).casefold()
    if finish_reason in {"length", "length_inferred"}:
        return "finish_reason_length"
    if getattr(response, "output_budget_exceeded", False):
        return "observed_output_exceeded_contract"
    return ""


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
