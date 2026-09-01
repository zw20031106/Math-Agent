from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json

from mathforge.agent_runtime.action_registry import ActionRegistry
from mathforge.agent_runtime.protocol import (
    AgentTurnPayload,
    AgentTurnPayloadParser,
    ParsedAgentTurn,
    LITE_PROTOCOL_SCHEMA_VERSION,
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
from mathforge.harness.problem_conditions import build_problem_condition_envelope
from mathforge.harness.reasoning_state import (
    ProgressDeltaParser,
    ReasoningState,
    RoundDelta,
)
from mathforge.harness.truncation import (
    ProofBackbone,
    TruncationAssessment,
    rebuild_candidate_from_state,
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
_ACTION_REGISTRY = ActionRegistry()


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
    # Full public checkpoint snapshot used only for deterministic recovery.
    # Normal prompts continue to use the token-budgeted reasoning_state_json.
    checkpoint_state_json: str = ""


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
        protocol_variant: str = PROTOCOL_SCHEMA_VERSION,
        semantic_payload: bool = False,
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
                "Public protocol mode is synthesize。严谨求解并保持可独立验证；方法简述仅作 diversity signal。"
                "若提供 ReasoningState，保留 ProblemFrame、Claim 依赖并列出未闭义务。"
            ),
            autonomous=autonomous,
            compact=compact,
            protocol_variant=protocol_variant,
            semantic_payload=semantic_payload,
        )

    def compile_progress_prompt(
        self,
        request: SolverRequest,
        *,
        mode: str,
        autonomous: bool = False,
        protocol_variant: str = PROTOCOL_SCHEMA_VERSION,
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
            protocol_variant=protocol_variant,
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
        protocol_variant: str = PROTOCOL_SCHEMA_VERSION,
        semantic_payload: bool = False,
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
                "Public protocol mode is synthesize。仅用分配的核心方法独立求解；方法简述仅作 diversity signal。"
            ),
            autonomous=autonomous,
            compact=compact,
            protocol_variant=protocol_variant,
            semantic_payload=semantic_payload,
        )

    def compile_progress_prompt(
        self,
        request: SolverRequest,
        *,
        mode: str,
        autonomous: bool = False,
        protocol_variant: str = PROTOCOL_SCHEMA_VERSION,
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
                "只推进隔离的 Alternative 状态；发布自己的候选前不得推断或请求 Primary 候选。"
            ),
            autonomous=autonomous,
            protocol_variant=protocol_variant,
        )


@dataclass(frozen=True)
class AutonomousSolverTurn:
    parsed: ParsedAgentTurn
    delta: RoundDelta | None = None
    candidate: CandidateSolution | None = None
    truncation_assessment: TruncationAssessment | None = None

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

    def _apply_replan_ack_if_required(
        self,
        response: str,
        parsed: ParsedAgentTurn | None,
        budget: CallBudget,
    ) -> None:
        runtime = budget.agent_runtime
        protocol_turn_id = str(getattr(response, "protocol_turn_id", ""))
        if runtime is None or not protocol_turn_id or not runtime.replan_ack_required(
            protocol_turn_id
        ):
            return
        strict_ack = bool(getattr(budget, "require_scheduler_binding", False))
        marker = None
        if parsed is not None:
            marker = parsed.payload.public_state_delta.get("replan_ack")
            if not isinstance(marker, dict):
                marker = parsed.payload.result_payload.get("replan_ack")
        if isinstance(marker, dict):
            applied_version = marker.get("plan_version")
            application_decision = marker.get("decision", "")
        else:
            applied_version = None
            application_decision = ""
        barrier = runtime.replan_barrier or {}
        if applied_version is None or not str(application_decision).strip():
            if strict_ack:
                self._fail_agent_turn(response, budget, "replan_ack_required")
                raise ModelResponseError("replan_ack_required")
            applied_version = barrier.get("to_version")
            application_decision = "legacy_turn_applied"
        try:
            runtime.acknowledge_replan_from_turn(
                protocol_turn_id,
                int(applied_version),
                str(application_decision),
                strict=strict_ack,
            )
            runtime.resume_replan_if_ready()
        except (KeyError, RuntimeError, TypeError, ValueError) as error:
            self._fail_agent_turn(response, budget, "replan_ack_invalid")
            raise ModelResponseError("replan_ack_invalid") from error

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
                    stage_timeout_seconds=budget.stage_timeout_seconds(
                        "lemma_curator"
                        if stage == "lemma"
                        else (
                            "solver_candidate_proof"
                            if request.problem.response_mode == "proof_full"
                            else "solver_candidate_standard"
                        )
                    ),
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
                sum(len(message["content"]) for message in attempt_messages),
                components=(
                    compilation.prompt_component_tokens
                    if attempt == 0
                    else {}
                ),
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
                    response_mode=request.problem.response_mode,
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
            # The legacy bounded Solver turn keeps its contract-retry loop;
            # long-horizon autonomous turns below opt into degradation after
            # this strict path has had a chance to repair the response.
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
            stage_timeout_seconds=budget.stage_timeout_seconds(
                "solver_compact_synthesis"
            ),
        )
        budget.record_prompt_chars(
            sum(len(message["content"]) for message in compilation.messages),
            components=compilation.prompt_component_tokens,
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
            response_mode=request.problem.response_mode,
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
        candidate.assurance = "emergency"
        candidate.degraded = True
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
            stage_timeout_seconds=budget.stage_timeout_seconds("solver_progress"),
        )
        budget.record_prompt_chars(
            sum(len(message["content"]) for message in compilation.messages),
            components=compilation.prompt_component_tokens,
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
        protocol_variant: str = PROTOCOL_SCHEMA_VERSION,
    ) -> AutonomousSolverTurn:
        compilation = solver.compile_progress_prompt(
            request,
            mode=mode,
            autonomous=True,
            protocol_variant=protocol_variant,
        )
        runtime = budget.agent_runtime
        replan_barrier = runtime.replan_barrier if runtime is not None else None
        if replan_barrier is not None and replan_barrier.get("status") == "paused":
            compilation.messages[-1]["content"] += (
                "\n\nA new authoritative plan is paused at a replan barrier. "
                "Apply that plan in this real Solver Turn and include this exact "
                "public marker inside public_state_delta while preserving the "
                "normal progress fields: replan_ack={\"plan_version\": "
                f"{int(replan_barrier['to_version'])}, \"decision\": \"apply\"}}."
            )
        stage = "primary" if solver.role == "PrimarySolver" else "alternative"
        budget.consume(
            stage=stage,
            optional=optional,
            action_category="speculative_exploration",
            stage_timeout_seconds=budget.stage_timeout_seconds("solver_progress"),
        )
        budget.record_prompt_chars(
            sum(len(message["content"]) for message in compilation.messages),
            components=compilation.prompt_component_tokens,
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
                _ACTION_REGISTRY.prompt_actions(
                    solver.role,
                    phase="progress",
                )
            ),
            truncated=_response_was_truncated(response),
            truncation_reason=_response_truncation_reason(response),
            protocol_variant=protocol_variant,
            task_result_type="ProgressArtifact",
            progress_summary="public progress turn",
        )
        truncation_assessment = TruncationAssessment.assess(
            response,
            required_fields=("action", "public_state_delta", "progress_summary"),
        )
        if parsed.payload.task_result_type not in {
            "ProgressArtifact",
            "ToolRequestArtifact",
            "CheckpointArtifact",
        }:
            self._fail_agent_turn(response, budget, "agent_turn_result_type_invalid")
            raise ModelResponseError("agent_turn_result_type_invalid")
        delta = None
        public_state_delta = dict(parsed.payload.public_state_delta)
        public_state_delta.pop("replan_ack", None)
        if public_state_delta:
            try:
                delta = ProgressDeltaParser().parse(
                    json.dumps(
                        public_state_delta,
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
        self._apply_replan_ack_if_required(response, parsed, budget)
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
        return AutonomousSolverTurn(
            parsed=parsed,
            delta=delta,
            truncation_assessment=truncation_assessment,
        )

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
        protocol_variant: str = PROTOCOL_SCHEMA_VERSION,
    ) -> AutonomousSolverTurn:
        compilation = solver.compile_prompt(
            request,
            autonomous=True,
            compact=compact,
            protocol_variant=protocol_variant,
            semantic_payload=(protocol_variant == LITE_PROTOCOL_SCHEMA_VERSION),
        )
        runtime = budget.agent_runtime
        replan_barrier = runtime.replan_barrier if runtime is not None else None
        if replan_barrier is not None and replan_barrier.get("status") == "paused":
            compilation.messages[-1]["content"] += (
                "\n\nA new authoritative plan is paused at a replan barrier. "
                "Apply that plan in this real Solver Turn and include this exact "
                "public marker inside public_state_delta while preserving the "
                "candidate payload: replan_ack={\"plan_version\": "
                f"{int(replan_barrier['to_version'])}, \"decision\": \"apply\"}}."
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
            stage_timeout_seconds=budget.stage_timeout_seconds(turn_kind),
        )
        budget.record_prompt_chars(
            sum(len(message["content"]) for message in compilation.messages),
            components=compilation.prompt_component_tokens,
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
        try:
            parsed = self._parse_agent_turn(
                response,
                budget,
                allowed_actions=_ACTION_REGISTRY.prompt_actions(
                    solver.role,
                    phase="candidate",
                ),
                truncated=_response_was_truncated(response),
                truncation_reason=_response_truncation_reason(response),
                protocol_variant=protocol_variant,
                task_result_type="CandidateArtifact",
                progress_summary="candidate turn",
            )
        except ModelResponseError:
            # A damaged candidate cannot silently bypass a paused replan
            # barrier.  Legacy profiles may still bind the real turn using
            # the compatibility acknowledgement path; strict competition
            # profiles require the explicit public marker.
            self._apply_replan_ack_if_required(response, None, budget)
            candidate = self._parser.recover_answer_candidate(
                response,
                candidate_id=request.candidate_id,
                role=solver.role,
                answer_type=request.problem.answer_type,
                planned_method_family=request.method_family,
            )
            if candidate is not None:
                rebuilt = self._rebuild_from_public_state(
                    request,
                    candidate,
                    role=solver.role,
                )
                if rebuilt is not None:
                    candidate = rebuilt
                elif (
                    request.reasoning_state_json.strip()
                    or request.checkpoint_state_json.strip()
                ):
                    raise ModelResponseError(
                        "stateful_candidate_rebuild_unavailable"
                    )
                return self._recovered_autonomous_candidate(
                    response,
                    candidate,
                    budget,
                    recovery_reason=(
                        "answer_salvaged_from_truncated_response"
                        if _response_was_truncated(response)
                        else "complete_answer_from_damaged_agent_turn"
                    ),
                )
            if not _response_was_truncated(response):
                raise
            response = self._retry_truncated_answer(
                solver,
                request,
                budget,
                stage=stage,
                input_artifact_ids=input_artifact_ids,
            )
            self._apply_replan_ack_if_required(response, None, budget)
            candidate = self._parser.recover_answer_candidate(
                response,
                candidate_id=request.candidate_id,
                role=solver.role,
                answer_type=request.problem.answer_type,
                planned_method_family=request.method_family,
            )
            if candidate is None:
                raise
            rebuilt = self._rebuild_from_public_state(
                request,
                candidate,
                role=solver.role,
            )
            if rebuilt is not None:
                candidate = rebuilt
            elif (
                request.reasoning_state_json.strip()
                or request.checkpoint_state_json.strip()
            ):
                raise ModelResponseError("stateful_candidate_rebuild_unavailable")
            return self._recovered_autonomous_candidate(
                response,
                candidate,
                budget,
                recovery_reason="answer_recovered_by_compact_retry",
            )
        self._apply_replan_ack_if_required(response, parsed, budget)
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
                response_mode=request.problem.response_mode,
            )
        except SchemaValidationError as error:
            self._fail_agent_turn(response, budget, "candidate_schema_invalid")
            budget.record_model_response_validation(
                getattr(response, "model_call_index", None),
                "candidate_schema_invalid",
                rejected=True,
            )
            raise ModelResponseError("candidate_schema_invalid") from error
        validation_code, rejected = candidate_response_validation(
            candidate,
            allow_degraded=True,
        )
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

        # A body that is structurally damaged but still yielded a public
        # answer must be rebuilt from the last Host checkpoint.  A balanced
        # payload with only a provider length marker remains a probable (not
        # definite) truncation and keeps the compatibility path used by the
        # existing simple-candidate profile.
        truncation_assessment = TruncationAssessment.assess(
            response,
            required_fields=("action", "result_payload"),
        )
        if parsed.partial and truncation_assessment.status in {
            "DEFINITE_TRUNCATION",
            "STRUCTURAL_DAMAGE",
        }:
            rebuilt = self._rebuild_from_public_state(
                request,
                candidate,
                role=solver.role,
            )
            if rebuilt is not None:
                candidate = rebuilt
                return self._recovered_autonomous_candidate(
                    response,
                    candidate,
                    budget,
                    recovery_reason="stateful_candidate_rebuilt_from_truncated_body",
                )
            if (
                request.reasoning_state_json.strip()
                or request.checkpoint_state_json.strip()
            ):
                self._fail_agent_turn(
                    response,
                    budget,
                    "stateful_candidate_rebuild_unavailable",
                )
                raise ModelResponseError("stateful_candidate_rebuild_unavailable")
        budget.record_model_response_validation(
            getattr(response, "model_call_index", None),
            validation_code,
            rejected=False,
        )
        candidate.planned_method_family = request.method_family
        candidate.validate()
        self._complete_agent_turn(response, budget)
        return AutonomousSolverTurn(
            parsed=parsed,
            candidate=candidate,
            truncation_assessment=truncation_assessment,
        )

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
            stage_timeout_seconds=budget.stage_timeout_seconds(
                "solver_compact_synthesis"
            ),
        )
        if request.reasoning_state_json.strip() or request.checkpoint_state_json.strip():
            # Stateful recovery keeps the public frontier and asks for a
            # complete Candidate artifact.  The answer-only retry remains a
            # last-resort compatibility path for callers that have no public
            # checkpoint at all.
            compilation = solver.compile_prompt(
                request,
                autonomous=True,
                compact=True,
            )
            messages = compilation.messages
        else:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "Solve the supplied problem. Output only the exact final "
                        "answer without labels, delimiters, explanations, or JSON."
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

    @staticmethod
    def _rebuild_from_public_state(
        request: SolverRequest,
        recovered: CandidateSolution,
        *,
        role: str,
    ) -> CandidateSolution | None:
        state_json = (
            request.checkpoint_state_json
            if request.checkpoint_state_json.strip()
            else request.reasoning_state_json
        )
        if not state_json.strip():
            return None
        try:
            payload = json.loads(state_json)
            if isinstance(payload, dict):
                # Compressed prompt projections contain additional metadata;
                # recovery reads only the canonical public state fields.
                allowed = {
                    "schema_version",
                    "state_id",
                    "version",
                    "problem_frame",
                    "subgoal_ledger",
                    "claim_ledger",
                    "open_obligations",
                    "evidence_refs",
                    "tool_results",
                    "contradictions",
                    "strategy",
                    "rounds",
                    "session_id",
                    "branch_id",
                    "agent_id",
                }
                payload = {key: value for key, value in payload.items() if key in allowed}
            state = ReasoningState.from_dict(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        backbone = ProofBackbone.from_state(state)
        return rebuild_candidate_from_state(
            state,
            final_answer=recovered.final_answer,
            candidate_id=request.candidate_id,
            role=role,
            method=request.method_family,
            answer_type=request.problem.answer_type,
            proof_backbone=backbone,
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
        candidate.assurance = (
            "recovered"
            if "stateful_rebuild" in " ".join(candidate.contract_deviations)
            or candidate.parse_status == "truncated_candidate_rebuilt"
            else "answer_salvaged"
        )
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
        truncation_assessment = TruncationAssessment.assess(
            response,
            required_fields=("action", "result_payload"),
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
        return AutonomousSolverTurn(
            parsed=parsed,
            candidate=candidate,
            truncation_assessment=truncation_assessment,
        )

    @staticmethod
    def _parse_agent_turn(
        response: str,
        budget: CallBudget,
        *,
        allowed_actions: tuple[str, ...],
        truncated: bool,
        truncation_reason: str,
        protocol_variant: str = PROTOCOL_SCHEMA_VERSION,
        task_result_type: str = "",
        progress_summary: str = "",
    ) -> ParsedAgentTurn:
        try:
            parser = AgentTurnPayloadParser()
            if protocol_variant == LITE_PROTOCOL_SCHEMA_VERSION:
                try:
                    parsed = parser.parse_lite(
                        response,
                        allowed_actions=allowed_actions,
                        truncated=truncated,
                        truncation_reason=truncation_reason,
                    ).to_agent_turn(
                        task_result_type=task_result_type,
                        progress_summary=progress_summary,
                    )
                except (TypeError, ValueError):
                    # P1 is additive.  A provider that still emits the P0
                    # envelope remains parseable during the experiment, while
                    # the strict lite parser continues to reject it in tests.
                    parsed = parser.parse(
                        response,
                        allowed_actions=allowed_actions,
                        truncated=truncated,
                        truncation_reason=truncation_reason,
                    )
                    parsed = ParsedAgentTurn(
                        payload=parsed.payload,
                        response_sha256=parsed.response_sha256,
                        partial=parsed.partial,
                        truncation_reason=parsed.truncation_reason,
                        parse_tier=f"lite_compat:{parsed.parse_tier}",
                        recovery_reason="provider_emitted_p0_envelope",
                        assurance_degradation=parsed.assurance_degradation,
                    )
            else:
                parsed = parser.parse(
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
    envelope = build_problem_condition_envelope(problem)
    fields = (
        ("Response mode", [problem.response_mode]),
        ("Answer type", [problem.answer_type]),
        ("Structural difficulty", problem.difficulty_features),
        ("Suggested decomposition", problem.subproblem_hints),
    )
    lines = [
        "Host-parsed public problem structure:",
        envelope.to_prompt(include_target=False),
        f"- Target kind: {problem.target_kind or 'unspecified'}",
    ]
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
        or str(getattr(response, "truncation_status", "")).casefold()
        == "truncated"
        or str(getattr(response, "finish_reason", "")).casefold()
        in {"length", "length_inferred"}
    )


def _response_truncation_reason(response: str) -> str:
    if str(getattr(response, "truncation_status", "")).casefold() == "truncated":
        return "truncation_status_truncated"
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
