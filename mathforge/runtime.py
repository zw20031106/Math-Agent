from __future__ import annotations

from typing import Any, Callable
from dataclasses import dataclass, replace
import json
from time import perf_counter

from mathforge.agents.registry import PromptContractLoader, SkillRegistry
from mathforge.agents.skill_selector import DynamicSkillSelector
from mathforge.agents.router_planner import RouterPlanner, method_families_for
from mathforge.config import HarnessConfig, load_competition_config
from mathforge.harness.allocation import CallAllocationPlan
from mathforge.harness.adaptive_fanout import AdaptiveFanoutPolicy
from mathforge.agent_runtime.session_call_budget import SessionCallBudget
from mathforge.agent_runtime.definitions import AgentRegistry
from mathforge.agent_runtime.runtime import SessionAgentRuntime
from mathforge.agent_runtime.autonomy import AgentProgressTracker
from mathforge.harness.budget import CallBudget
from mathforge.harness.debug import DebugSink, sanitized_failure_record
from mathforge.harness.errors import (
    BudgetExceeded,
    ModelTransportError,
    classify_failure,
)
from mathforge.harness.fallback import FallbackSolver
from mathforge.harness.fingerprints import (
    request_fingerprint,
    semantic_fingerprint,
)
from mathforge.harness.context_budget import ModelContextBudget
from mathforge.harness.metrics import collect_run_metrics
from mathforge.harness.effective_config import (
    build_effective_config_snapshot,
)
from mathforge.harness.model_policy import (
    stage_sequence_feasible,
    stage_sequence_reserve_seconds,
)
from mathforge.harness.reasoning_state import (
    LongHorizonPlan,
    LongHorizonPolicy,
    REASONING_STATE_MAX_TOKENS,
    ReasoningState,
    ReasoningStateCompressor,
)
from mathforge.harness.proof_graph import build_claim_evidence_graph
from mathforge.agents.solver import (
    AlternativeSolver,
    PrimarySolver,
    SolverExecutor,
    SolverRequest,
)
from mathforge.agents.lemma_curator import (
    LLMLemmaCuratorAgent,
    LLMLemmaRequest,
)
from mathforge.agents.peer_review import SolverPeerReviewAgent
from mathforge.harness.orchestration import (
    BranchFailure,
    CandidateOrchestrator,
    FanoutResult,
    candidate_failure_trace_payload,
    candidate_trace_payload,
    public_candidate_content,
)
from mathforge.harness.provider import ModelCallGate, OfficialClientProvider
from mathforge.harness.session import create_session
from mathforge.harness.stages import (
    CandidateStage,
    ContextRouteStage,
    EvidenceStage,
    ProofStage,
)
from mathforge.harness.state import RuntimePhase
from mathforge.harness.trace import TraceBuilder
from mathforge.harness.trace_summary import (
    build_case_trace_summary,
    build_transport_summary,
)
from mathforge.harness.terminalizer import (
    MINIMAL_FALLBACK_RESPONSE,
    NoThrowTerminalizer,
    minimal_fallback_metrics,
)
from mathforge.output.answer_validator import AnswerValidator
from mathforge.output.deterministic_formatter import (
    DeterministicFormatter,
    bound_final_response,
    canonical_final_response,
)
from mathforge.output.loop_health import (
    build_closed_loop_health,
    minimal_closed_loop_health,
)
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.parsing.solution_parser import SolutionParser
from mathforge.tools.executor import ToolExecutor
from mathforge.harness.tool_feedback import ToolFeedbackController
from mathforge.verification.evidence import (
    EvidenceLedger,
    is_fatal_hard_failure,
    is_semantic_hard_pass,
)
from mathforge.verification.arbitration import ArbitrationPolicy
from mathforge.context.errors import ContextBudgetExceeded
from mathforge.context.role_views import RoleContextFactory
from mathforge.memory.blackboard import MemoryBlackboard
from mathforge.memory.frozen_lemma_store import FrozenLemmaStore
from mathforge.memory.problem_memo import ProblemMemo
from mathforge.harness.lemma_loop import VerifiedLemmaLoop
from mathforge.model_identity import ModelIdentity
from mathforge.retrieval.retriever import Retriever
from mathforge.resources import resource_path
from mathforge.provenance import build_run_provenance
from mathforge.agents.repair import RepairAgent
from mathforge.harness.repair import ClaimRepairService
from mathforge.verification.repair_scope import (
    actionable_verifier_failures,
    claim_impact_closure,
)
from mathforge.agents.finalizer import LLMFinalizer
from mathforge.agents.verifier import VerifierSkepticAgent
from mathforge.agents.verification_closure import VerificationClosureAgent
from mathforge.verification.admission import (
    CandidateAdmissionError,
    CandidateAdmissionGate,
)
from mathforge.verification.cross_review import (
    CandidateConflictMatrix,
    CandidateReviewSummary,
    has_reviewable_work,
)
from mathforge.verification.candidate_pool import CandidatePool
from mathforge.tools.shadow_solver import ShadowOutcome
from mathforge.verification.answer_normalization import canonical_answer


@dataclass
class _AutonomousBranch:
    role: str
    candidate_id: str
    solver: PrimarySolver | AlternativeSolver
    method_family: str
    forbidden_method_families: tuple[str, ...]
    context_view: Any
    skill_context: str
    state: ReasoningState
    mode: str = "explore"
    status: str = "exploring"
    stop_reason: str = ""
    candidate: Any = None


_ROLE_CONTRACT_DIRECTORIES = {
    "RouterPlanner": "router_planner",
    "PrimarySolver": "primary_solver",
    "AlternativeSolver": "alternative_solver",
    "LemmaCurator": "lemma_curator",
    "VerifierSkeptic": "verifier_skeptic",
    "RepairAgent": "repair",
    "LLMFinalizer": "finalizer",
}

_SKILL_RUNTIME_ROLES = (
    "PrimarySolver",
    "AlternativeSolver",
    "LemmaCurator",
    "VerifierSkeptic",
    "RepairAgent",
    "LLMFinalizer",
)

_PUBLIC_METADATA_KEYS = (
    "idx",
    "id",
    "benchmark_nonce",
    "case_id",
    "problem_type",
    "answer_type",
    "response_mode",
)


def _build_call_allocation(
    budget: CallBudget,
    **kwargs: Any,
):
    max_calls = int(kwargs.pop("max_calls"))
    governor = budget.resource_governor
    if governor is not None:
        return governor.activation_plan(
            used_calls=budget.used_calls,
            **kwargs,
        )
    return CallAllocationPlan.build(max_calls=max_calls, **kwargs)


def _apply_stage_allocation(
    budget: CallBudget,
    allocation: Any,
) -> None:
    if budget.resource_governor is None:
        budget.set_allocation_plan(allocation)


def _public_metadata(metadata: Any) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    result: dict[str, Any] = {}
    for key in _PUBLIC_METADATA_KEYS:
        value = metadata.get(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            result[key] = value
        elif isinstance(value, list) and all(
            isinstance(item, (str, int, float, bool)) or item is None
            for item in value[:32]
        ):
            result[key] = list(value[:32])
    return result


class MathForgeHarness:
    """Thread-safe facade over the injected official model client."""

    def __init__(
        self,
        client: Any,
        config: HarnessConfig | None = None,
        *,
        debug_sink: DebugSink | None = None,
        model_identity: ModelIdentity | None = None,
        trace_sink_factory: (
            Callable[
                [str, dict[str, Any]],
                Callable[[dict[str, Any]], None] | None,
            ]
            | None
        ) = None,
    ) -> None:
        self._config = config or load_competition_config()
        self._agent_definitions = AgentRegistry.default()
        self._debug_sink = debug_sink
        self._trace_sink_factory = trace_sink_factory
        self._context_budget = ModelContextBudget(
            context_window_tokens=self._config.model_context_window_tokens,
            safety_margin_tokens=self._config.context_safety_margin_tokens,
        )
        gate = ModelCallGate(
            self._config.model_max_concurrency,
            requests_per_minute=self._config.model_requests_per_minute,
            rate_limit_window_seconds=self._config.rate_limit_window_seconds,
            transport_attempt_reservation=(
                self._config.transport_attempt_reservation
            ),
            max_background_tails=self._config.max_background_model_tails,
            late_registry_limit=self._config.late_result_registry_max_entries,
        )
        self._model_gate = gate
        self._provider = OfficialClientProvider(
            client,
            gate,
            self._context_budget,
            stage_execution_policy=self._config.stage_execution_policy,
        )
        self._fallback = FallbackSolver()
        self._problem_parser = ProblemParser()
        self._solution_parser = SolutionParser()
        self._answer_validator = AnswerValidator()
        self._candidate_stage = CandidateStage(
            CandidateAdmissionGate(self._answer_validator)
        )
        self._formatter = DeterministicFormatter()
        self._contracts = PromptContractLoader()
        self._context_route_stage = ContextRouteStage(
            RouterPlanner(contracts=self._contracts),
            RoleContextFactory(),
        )
        self._skills = SkillRegistry()
        self._dynamic_skills = DynamicSkillSelector(self._skills)
        self._solver_executor = SolverExecutor(self._provider, self._solution_parser)
        self._candidate_orchestrator = CandidateOrchestrator(
            self._solver_executor,
            self._contracts,
        )
        self._tool_executor = ToolExecutor(use_mcp=self._config.use_mcp)
        self._tool_feedback = ToolFeedbackController(self._tool_executor)
        self._arbitration = ArbitrationPolicy(self._tool_executor)
        self._lemma_loop = VerifiedLemmaLoop()
        self._llm_lemma_curator = LLMLemmaCuratorAgent(
            self._provider,
            self._contracts,
        )
        self._peer_review_agent = SolverPeerReviewAgent(
            self._provider,
            self._contracts,
        )
        self._retriever = Retriever() if self._config.enable_rag else None
        self._evidence_stage = EvidenceStage(self._tool_executor)
        self._proof_stage = ProofStage()
        self._repair_agent = RepairAgent(
            self._provider,
            self._solution_parser,
            self._contracts,
        )
        self._finalizer = (
            LLMFinalizer(
                self._provider,
                self._solution_parser,
                self._formatter,
                self._contracts,
            )
            if self._config.enable_finalizer
            else None
        )
        self._adaptive_fanout = AdaptiveFanoutPolicy()
        self._long_horizon_policy = LongHorizonPolicy()
        self._reasoning_state_compressor = ReasoningStateCompressor(
            self._context_budget.token_counter
        )
        self._shadow_executor = (
            ToolExecutor(
                default_timeout=min(5.0, self._config.max_tool_seconds),
                use_mcp=False,
            )
            if self._config.enable_shadow
            else None
        )
        frozen_lemma_store = (
            FrozenLemmaStore(
                resource_path("data", "frozen_lemmas.jsonl"),
                resource_path("data", "frozen_lemmas_manifest.json"),
            )
            if self._config.enable_frozen_lemma_store
            else None
        )
        frozen_lemma_disabled_reason = (
            "config_disabled"
            if frozen_lemma_store is None
            else ""
        )
        if frozen_lemma_store is not None and frozen_lemma_store.count == 0:
            frozen_lemma_disabled_reason = "empty_store"
            frozen_lemma_store = None
        self._frozen_lemma_store = frozen_lemma_store
        self._frozen_lemma_disabled_reason = frozen_lemma_disabled_reason
        self._effective_config_snapshot = build_effective_config_snapshot(
            self._config,
            self._contracts,
            frozen_lemma_store_requested=(
                self._config.enable_frozen_lemma_store
            ),
            frozen_lemma_store_count=(
                self._frozen_lemma_store.count
                if self._frozen_lemma_store is not None
                else 0
            ),
            frozen_lemma_store_disabled_reason=(
                self._frozen_lemma_disabled_reason
            ),
        )
        self._verifier_agent = VerifierSkepticAgent(self._provider, self._contracts)
        self._verification_closure_agent = VerificationClosureAgent(
            self._provider,
            self._contracts,
        )
        self._run_provenance = build_run_provenance(
            self._config,
            contracts=self._contracts,
            skills=self._skills,
            tool_manifest=self._tool_executor.manifest,
            model_identity=model_identity,
        )
        identity = ModelIdentity.from_dict(self._run_provenance.model_identity)
        self._provenance = {
            "config_schema_version": self._config.schema_version,
            "config_profile": self._config.profile,
            "config_status": self._config.status,
            "config_hash": self._config.fingerprint,
            "prompt_hash": self._contracts.fingerprint,
            "skill_hash": self._skills.fingerprint,
            "rag_hash": self._run_provenance.rag["knowledge_db_sha256"],
            "tool_hash": self._tool_executor.fingerprint,
            "code_commit": self._run_provenance.code_commit,
            "code_dirty": self._run_provenance.code_dirty,
            "tokenizer_repository": self._run_provenance.tokenizer["repository"],
            "tokenizer_revision": self._run_provenance.tokenizer["revision"],
            "tokenizer_json_sha256": self._run_provenance.tokenizer[
                "tokenizer_json_sha256"
            ],
            "tokenizer_config_sha256": self._run_provenance.tokenizer[
                "tokenizer_config_sha256"
            ],
            "tokenizer_chat_template_sha256": self._run_provenance.tokenizer[
                "chat_template_sha256"
            ],
            "tokenizer_fallback_sha256": self._run_provenance.tokenizer[
                "fallback_sha256"
            ],
            **identity.to_dict(),
            "provenance_hash": self._run_provenance.fingerprint,
        }

    def solve(self, problem: str, metadata: dict) -> dict:
        normalized_problem = problem if isinstance(problem, str) else str(problem)
        safe_metadata = _public_metadata(metadata)
        session = create_session(
            normalized_problem,
            safe_metadata,
            SessionCallBudget(
                max_calls=(
                    self._config.max_logical_model_calls_per_problem
                    if self._config.model_call_policy == "adaptive_bounded"
                    else self._config.max_model_calls
                ),
                max_tokens=self._config.max_model_tokens,
                soft_deadline_seconds=self._config.soft_deadline_seconds,
                exploration_deadline_seconds=self._config.exploration_deadline_seconds,
                hard_deadline_seconds=self._config.hard_deadline_seconds,
                deterministic_finalize_reserve_seconds=(
                    self._config.deterministic_finalize_reserve_seconds
                ),
                model_call_start_margin_seconds=(
                    self._config.model_call_start_margin_seconds
                ),
                model_queue_budget_seconds=(
                    self._config.model_queue_budget_seconds
                ),
                max_claims=self._config.max_claims,
                max_tool_calls=self._config.max_tool_calls,
                max_isolated_tool_calls=self._config.max_isolated_tool_calls,
                max_tool_seconds=self._config.max_tool_seconds,
                max_evidence_records=self._config.max_evidence_records,
                max_prompt_chars_total=self._config.max_prompt_chars_total,
                token_limit_mode=(
                    "dynamic_context"
                    if self._config.primary_max_tokens == 0
                    else "configured_cap"
                ),
                model_context_window_tokens=(
                    self._config.model_context_window_tokens
                ),
                context_safety_margin_tokens=(
                    self._config.context_safety_margin_tokens
                ),
                model_call_policy=self._config.model_call_policy,
                soft_call_checkpoints=self._config.soft_call_checkpoints,
                speculative_exploration_cutoff=(
                    self._config.speculative_exploration_cutoff
                ),
                closure_reserve_calls=self._config.closure_reserve_calls,
            ),
            raw_context_max_chars=self._config.raw_context_max_chars,
        )
        session.agent_runtime = SessionAgentRuntime(
            session.session_id,
            self._agent_definitions,
        )
        session.budget.bind_agent_runtime(session.agent_runtime)
        fingerprint_nonce = str(safe_metadata.get("benchmark_nonce", session.session_id))
        run_fingerprint = request_fingerprint(normalized_problem, fingerprint_nonce)
        trace_sink = None
        if self._trace_sink_factory is not None:
            try:
                trace_sink = self._trace_sink_factory(
                    session.session_id,
                    safe_metadata,
                )
            except Exception:
                trace_sink = None
        trace = TraceBuilder(
            session.trace_events,
            max_chars=self._config.trace_max_chars,
            max_events=self._config.trace_max_events,
            redacted_values=(
                [fingerprint_nonce]
                if "benchmark_nonce" in safe_metadata
                else []
            ),
            event_sink=trace_sink,
        )
        trace.add(
            "session_started",
            session_id=session.session_id,
            request_fingerprint=run_fingerprint,
            **self._provenance,
        )
        trace.add(
            "effective_config_snapshot",
            snapshot=self._effective_config_snapshot,
        )
        terminalizer = NoThrowTerminalizer()
        outcome = "fallback"
        error_code = ""
        failure: Exception | None = None
        failed_phase = RuntimePhase.CREATED
        selected_candidate_id = ""
        candidate_states: list[dict[str, Any]] = []
        last_safe_candidate: Any | None = None
        last_safe_checkpoint = ""
        final_response = MINIMAL_FALLBACK_RESPONSE
        problem_memo = ProblemMemo()
        shadow_outcome: ShadowOutcome | None = None
        frozen_lemma_hits = ()
        reasoning_plan = LongHorizonPlan(
            False,
            1,
            "not_planned",
            0.0,
        )
        reasoning_degraded_reason = ""

        def remember_safe_candidate(
            candidates: list[Any] | tuple[Any, ...],
            checkpoint: str,
        ) -> None:
            nonlocal last_safe_candidate, last_safe_checkpoint
            for item in candidates or ():
                if not str(getattr(item, "final_answer", "")).strip():
                    continue
                if any(
                    record.candidate_id == item.candidate_id
                    and is_fatal_hard_failure(record)
                    for record in session.evidence
                ):
                    continue
                last_safe_candidate = item
                last_safe_checkpoint = str(checkpoint)
                return

        try:
            session.budget.ensure_stage("problem_parser")
            session.problem_ir = self._problem_parser.parse(
                normalized_problem,
                metadata=safe_metadata,
            )
            session.problem_ir.validate()
            blackboard = MemoryBlackboard(session.working_memory)
            if self._shadow_executor is not None:
                shadow_outcome = problem_memo.get_or_compute(
                    "l0:deterministic_shadow",
                    lambda: self._run_shadow_probe(session.problem_ir),
                )
            if self._frozen_lemma_store is not None:
                frozen_store = self._frozen_lemma_store
                frozen_lemma_hits = problem_memo.get_or_compute(
                    "l1:frozen_lemma_retrieval",
                    lambda: frozen_store.retrieve(session.problem_ir),
                )
            if self._config.enable_memory:
                blackboard.publish(
                    "System",
                    "raw",
                    {"metadata": safe_metadata},
                )
                if frozen_lemma_hits:
                    blackboard.publish(
                        "System",
                        "lemma",
                        {
                            "source": "frozen_lemma_store",
                            "store_hash": self._frozen_lemma_store.store_hash,
                            "lemmas": [
                                {
                                    "lemma_id": hit.lemma.lemma_id,
                                    "statement": hit.lemma.statement,
                                    "domain": hit.lemma.domain,
                                    "assumptions": list(hit.lemma.assumptions),
                                    "preconditions": list(hit.lemma.preconditions),
                                    "conclusion": hit.lemma.conclusion,
                                    "proof_outline_public": list(
                                        hit.lemma.proof_outline_public
                                    ),
                                    "content_hash": hit.lemma.content_hash,
                                }
                                for hit in frozen_lemma_hits
                            ],
                        },
                    )
            trace.add(
                "frozen_lemma_cache",
                requested=self._config.enable_frozen_lemma_store,
                enabled=self._frozen_lemma_store is not None,
                disabled_reason=self._frozen_lemma_disabled_reason,
                record_count=(
                    self._frozen_lemma_store.count
                    if self._frozen_lemma_store is not None
                    else 0
                ),
                store_hash=(
                    self._frozen_lemma_store.store_hash
                    if self._frozen_lemma_store is not None
                    else ""
                ),
                hits=[
                    hit.to_trace_dict()
                    for hit in frozen_lemma_hits
                ],
                runtime_write_count=0,
            )
            trace.add(
                "problem_parsed",
                problem_type=session.problem_ir.problem_type,
                answer_type=session.problem_ir.answer_type,
                response_mode=session.problem_ir.response_mode,
                answer_type_confidence=(
                    session.problem_ir.answer_type_confidence
                ),
                target_phrase=session.problem_ir.target_phrase,
                target_kind=session.problem_ir.target_kind,
                parser_confidence=session.problem_ir.parser_confidence,
                assumptions=session.problem_ir.assumptions,
                definitions=session.problem_ir.definitions,
                quantifiers=session.problem_ir.quantifiers,
                constraints=session.problem_ir.constraints,
                ambiguities=session.problem_ir.ambiguities,
                difficulty_features=(
                    session.problem_ir.difficulty_features
                ),
                subproblem_hints=session.problem_ir.subproblem_hints,
                domains=session.problem_ir.domains,
                risk_flags=session.problem_ir.risk_flags,
            )
            if self._config.enable_proof_obligations:
                session.problem_obligations = (
                    self._proof_stage.plan_problem(session.problem_ir)
                )
            trace.add(
                "problem_obligations_planned",
                enabled=self._config.enable_proof_obligations,
                timing="before_solver",
                obligations=[
                    obligation.to_dict()
                    for obligation in session.problem_obligations
                ],
            )
            self._transition(
                session,
                trace,
                RuntimePhase.CREATED,
                RuntimePhase.PARSED,
                "problem_parsed",
            )
            router_context = None
            router_enabled = self._config.enable_router
            potential_verifier = (
                self._config.enable_verifier
                and self._config.enable_evidence
                and self._config.enable_proof_obligations
            )
            router_unreachable = False
            try:
                router_context = self._build_role_context(
                    session,
                    blackboard,
                    trace,
                    role="RouterPlanner",
                )
            except (ContextBudgetExceeded, BudgetExceeded):
                router_context = None
                trace.add(
                    "context_budget_infeasible",
                    role="RouterPlanner",
                    action="use_minimal_router_context",
                )
            router_outcome = self._context_route_stage.plan_authoritative(
                session.problem_ir,
                llm_chat=(
                    (
                        lambda **kwargs: self._provider.chat(
                            budget=session.budget,
                            stage="router",
                            turn_kind="router",
                            agent_id="RouterPlanner",
                            **kwargs,
                        )
                    )
                    if router_enabled
                    else None
                ),
                consume_call=(
                    (
                        lambda: session.budget.consume(
                            stage="router",
                            optional=False,
                            action_category="replan",
                        )
                    )
                    if router_enabled
                    else None
                ),
                max_tokens=self._config.primary_max_tokens,
                context_view=router_context,
                record_prompt_chars=(
                    session.budget.record_prompt_chars if router_enabled else None
                ),
            )
            session.route_plan = router_outcome.route_plan
            session.agent_plan = router_outcome.authoritative_plan
            router_protocol_refs = session.agent_runtime.publish_router_decision(
                route_payload=session.route_plan.to_dict(),
                plan=session.agent_plan,
            )
            if not self._config.enable_alternatives:
                session.route_plan = replace(session.route_plan, candidate_count=1)
            if not self._config.enable_lemma_loop:
                session.route_plan = replace(session.route_plan, use_lemma_loop=False)
            if not self._config.enable_rag:
                session.route_plan = replace(session.route_plan, use_rag=False)
            if session.budget.soft_expired():
                session.route_plan = replace(
                    session.route_plan,
                    candidate_count=1,
                    max_reasoning_rounds=1,
                    use_rag=False,
                    use_lemma_loop=False,
                    use_llm_finalizer=False,
                )
                trace.add(
                    "deadline_finalize",
                    stage="soft_cutoff",
                    disabled=["alternatives", "rag", "lemma", "finalizer"],
                )
            elif (
                not session.budget.can_start_exploration()
                and session.route_plan.candidate_count > 1
            ):
                session.route_plan = replace(
                    session.route_plan,
                    candidate_count=1,
                    max_reasoning_rounds=1,
                    use_lemma_loop=False,
                )
                trace.add("deadline_finalize", stage="before_fanout")
            verifier_required = (
                potential_verifier
                and session.route_plan.risk_level in {"medium", "high"}
            )
            session.reasoning_state = ReasoningState.initialize(
                session.problem_ir,
                strategy=(
                    session.route_plan.method_families[0]
                    if session.route_plan.method_families
                    else ""
                ),
            )
            pre_allocation_budget = session.budget.snapshot()
            autonomous_agents_enabled = bool(
                self._config.enable_long_horizon
                and self._config.model_call_policy == "adaptive_bounded"
                and self._provider_allows_optional_model_work()
            )
            reasoning_plan = (
                LongHorizonPlan(
                    False,
                    1,
                    "agent_action_governed",
                    0.0,
                )
                if autonomous_agents_enabled
                else self._long_horizon_policy.decide(
                    session.route_plan,
                    enabled=self._config.enable_long_horizon,
                    remaining_calls=pre_allocation_budget.remaining_calls,
                    remaining_seconds=pre_allocation_budget.remaining_seconds,
                    verifier_required=verifier_required,
                    alternatives_enabled=self._config.enable_alternatives,
                    provider_healthy=self._provider_allows_optional_model_work(),
                    maximum_queue_seconds=(
                        self._config.model_queue_budget_seconds
                    ),
                )
            )
            allocation = _build_call_allocation(
                session.budget,
                max_calls=self._config.max_model_calls,
                router_calls=session.budget.used_calls,
                candidate_count=(
                    max(2, session.route_plan.candidate_count)
                    if self._config.enable_alternatives
                    else session.route_plan.candidate_count
                ),
                verifier_required=verifier_required,
                repair_requested=False,
                lemma_requested=False,
                finalizer_requested=(
                    self._config.enable_finalizer
                    and session.route_plan.use_llm_finalizer
                ),
                primary_calls=(
                    1
                    if autonomous_agents_enabled
                    else reasoning_plan.planned_rounds
                ),
            )
            _apply_stage_allocation(session.budget, allocation)
            unreachable = list(allocation.unreachable_by_budget)
            if router_unreachable:
                unreachable.insert(0, "router")
            session.route_plan = replace(
                session.route_plan,
                candidate_count=1 + allocation.alternatives,
                use_llm_finalizer=(
                    session.route_plan.use_llm_finalizer
                    and allocation.finalizer_reserve > 0
                ),
            )
            if self._config.enable_memory:
                blackboard.publish(
                    "System",
                    "working",
                    {"route_plan": session.route_plan.to_dict()},
                )
            skill_compositions = (
                {
                    role: self._dynamic_skills.compose_for_role(
                        session.problem_ir,
                        role=role,
                        route_skill_names=(
                            session.route_plan.selected_skills
                        ),
                        max_chars=self._config.skill_char_budget,
                        state=session.reasoning_state,
                        selection_context="initial",
                    )
                    for role in _SKILL_RUNTIME_ROLES
                }
                if self._config.enable_skills
                else {}
            )
            role_skill_contexts = {
                role: composition.text
                for role, composition in skill_compositions.items()
            }
            if (
                session.route_plan.use_rag
                and session.budget.deadline.optional_work_allowed()
            ):
                session.budget.ensure_stage("rag", optional=True)
                retriever = self._retriever
                if retriever is None:
                    raise RuntimeError("enabled retriever was not constructed")
                retrieval_result = retriever.search_with_status(
                    session.problem_ir.normalized_problem,
                    subject=session.route_plan.primary_subject,
                    role="PrimarySolver",
                    top_k=3,
                )
                retrieval_hits = retrieval_result.hits
                retrieval_status = retrieval_result.status.value
                if session.budget.must_finalize():
                    retrieval_hits = []
                    retrieval_status = "discarded_by_deadline"
                    trace.add("deadline_finalize", stage="after_rag")
                cards = [hit.card for hit in retrieval_hits]
                injected_card_ids: list[str] = []
                if cards:
                    primary_context = role_skill_contexts.get(
                        "PrimarySolver",
                        "",
                    )
                    for card in cards:
                        block = (
                            f"## Reviewed knowledge: {card.title}\n{card.statement}\n"
                            f"Conditions: {', '.join(card.preconditions) or 'none'}\n"
                            f"Source: {card.source_ref} @ {card.source_version}"
                        )
                        separator = "\n\n" if primary_context else ""
                        if (
                            len(primary_context)
                            + len(separator)
                            + len(block)
                            > self._config.skill_char_budget
                        ):
                            continue
                        primary_context = f"{primary_context}{separator}{block}"
                        injected_card_ids.append(card.id)
                    role_skill_contexts["PrimarySolver"] = primary_context
                trace.add(
                    "retrieval_completed",
                    status=retrieval_status,
                    card_ids=[card.id for card in cards],
                    injected_card_ids=injected_card_ids,
                    ranking=[
                        {
                            "card_id": hit.card.id,
                            "trust_level": hit.card.trust_level,
                            "condition_score": hit.condition_score,
                            "bm25_score": round(hit.bm25_score, 8),
                            "source_version": hit.card.source_version,
                        }
                        for hit in retrieval_hits
                    ],
                )
            elif session.route_plan.use_rag:
                trace.add(
                    "deadline_finalize",
                    stage="before_rag",
                    disabled=["rag"],
                )
            trace.add(
                "route_planned",
                router_llm_attempted=router_outcome.llm_attempted,
                router_source=router_outcome.source,
                router_fallback_reason=router_outcome.fallback_reason,
                plan_id=session.agent_plan.plan_id,
                plan_version=session.agent_plan.version,
                parent_plan_id=session.agent_plan.parent_plan_id,
                original_condition_digest=(
                    session.agent_plan.original_condition_digest
                ),
                subgoals=[
                    item.to_dict() for item in session.agent_plan.subgoals
                ],
                task_proposals=[
                    item.to_dict()
                    for item in session.agent_plan.task_proposals
                ],
                **router_protocol_refs,
                primary_subject=session.route_plan.primary_subject,
                auxiliary_subject=session.route_plan.auxiliary_subject,
                risk_level=session.route_plan.risk_level,
                routing_confidence=session.route_plan.routing_confidence,
                ambiguity_margin=session.route_plan.ambiguity_margin,
                complexity_flags=session.route_plan.complexity_flags,
                subject_candidates=session.problem_ir.subject_candidates,
                selected_skills=session.route_plan.selected_skills,
                selected_tools=session.route_plan.selected_tools,
                method_families=session.route_plan.method_families,
                routing_reasons=self._context_route_stage.routing_reasons(
                    session.problem_ir,
                    session.route_plan,
                ),
            )
            trace.add(
                "reasoning_state_initialized",
                state_id=session.reasoning_state.state_id,
                state_version=session.reasoning_state.version,
                reasoning_state_schema_version=(
                    session.reasoning_state.schema_version
                ),
                problem_frame_digest=semantic_fingerprint(
                    session.reasoning_state.problem_frame.to_dict()
                ),
                preserved_invariants=[
                    "original_problem",
                    "definitions",
                    "quantifiers",
                    "constraints",
                    "target",
                    "claim_dependencies",
                    "open_obligations",
                ],
            )
            if autonomous_agents_enabled:
                trace.add(
                    "autonomous_solver_planned",
                    enabled=True,
                    fixed_planned_rounds=False,
                    governance=(
                        "agent_action+public_progress+resource_governor+deadline"
                    ),
                    remaining_calls=pre_allocation_budget.remaining_calls,
                    remaining_seconds=pre_allocation_budget.remaining_seconds,
                )
            else:
                trace.add(
                    "long_horizon_planned",
                    **reasoning_plan.to_dict(),
                    remaining_calls=pre_allocation_budget.remaining_calls,
                    remaining_seconds=pre_allocation_budget.remaining_seconds,
                )
            self._trace_dynamic_skill_selection(
                trace,
                skill_compositions,
                selection_context="initial",
            )
            trace.add(
                "call_allocation_planned",
                **{
                    **allocation.to_dict(),
                    "unreachable_by_budget": unreachable,
                },
            )
            session.route_plan.validate()
            self._transition(
                session,
                trace,
                RuntimePhase.PARSED,
                RuntimePhase.ROUTED,
                "route_planned",
            )
            solver_contexts = {
                "PrimarySolver": self._build_role_context(
                    session,
                    blackboard,
                    trace,
                    role="PrimarySolver",
                )
            }
            if session.route_plan.candidate_count > 1:
                solver_contexts["AlternativeSolver"] = self._build_role_context(
                    session,
                    blackboard,
                    trace,
                    role="AlternativeSolver",
                )
            self._transition(
                session,
                trace,
                RuntimePhase.ROUTED,
                RuntimePhase.CONTEXT_READY,
                "solver_context_ready",
            )
            primary_seed = None
            autonomous_summary: dict[str, Any] = {}
            if autonomous_agents_enabled:
                fanout, session.reasoning_state, autonomous_summary = (
                    self._run_autonomous_solver_fanout(
                        session,
                        trace,
                        role_skill_contexts=role_skill_contexts,
                        solver_contexts=solver_contexts,
                    )
                )
            elif reasoning_plan.enabled:
                (
                    primary_seed,
                    session.reasoning_state,
                    reasoning_degraded_reason,
                ) = self._run_long_horizon_primary(
                    session,
                    trace,
                    reasoning_plan,
                    skill_context=role_skill_contexts.get(
                        "PrimarySolver",
                        "",
                    ),
                    context_view=solver_contexts["PrimarySolver"],
                )
            if not autonomous_agents_enabled:
                fanout = self._candidate_orchestrator.fanout(
                    session.problem_ir,
                    session.route_plan,
                    role_skill_contexts.get("PrimarySolver", ""),
                    session.budget,
                    temperature=self._config.primary_temperature,
                    max_tokens=self._config.primary_max_tokens,
                    context_views=solver_contexts,
                    role_skill_contexts=role_skill_contexts,
                    event_callback=trace.add,
                    fanout_decider=(
                        lambda primary, budget: self._adaptive_fanout.decide(
                            session.route_plan,
                             primary,
                             budget,
                             required_stage_reserve=allocation.verifier,
                             shadow_consistency=self._shadow_consistency(
                                 primary,
                                 shadow_outcome,
                                 session.problem_ir.answer_type,
                             ),
                         )
                     ),
                    primary_candidate=primary_seed,
                 )
            primary_candidate = next(
                (
                    item
                    for item in fanout.candidates
                    if item.role == "PrimarySolver"
                ),
                None,
            )
            reasoning_stop_reason = "primary_candidate_unavailable"
            if primary_candidate is not None:
                try:
                    (
                        session.reasoning_state,
                        synthesis_summary,
                    ) = session.reasoning_state.apply_candidate(
                        primary_candidate
                    )
                except ValueError:
                    reasoning_degraded_reason = (
                        reasoning_degraded_reason
                        or "synthesis_state_transition_invalid"
                    )
                else:
                    try:
                        synthesis_state = self._compress_reasoning_state(
                            session.reasoning_state,
                            trace,
                        )
                    except ContextBudgetExceeded:
                        reasoning_degraded_reason = (
                            reasoning_degraded_reason
                            or "synthesis_state_budget_infeasible"
                        )
                        synthesis_state = None
                    trace.add(
                        "round_summary",
                        **synthesis_summary,
                        state_tokens=(
                            synthesis_state.state_tokens
                            if synthesis_state is not None
                            else 0
                        ),
                        state_counting_mode=(
                            synthesis_state.counting_mode
                            if synthesis_state is not None
                            else "unavailable"
                        ),
                        state_compressed=(
                            synthesis_state.compressed
                            if synthesis_state is not None
                            else False
                        ),
                        omitted_rounds=(
                            synthesis_state.omitted_rounds
                            if synthesis_state is not None
                            else 0
                        ),
                    )
                    reasoning_stop_reason = "candidate_synthesized"
            if self._config.enable_memory:
                blackboard.publish(
                    "System",
                    "working",
                    {
                        "reasoning_state": (
                            session.reasoning_state.to_dict()
                        ),
                        "projection": "public_read_only",
                    },
                )
            trace.add(
                "reasoning_loop_completed",
                state_id=session.reasoning_state.state_id,
                enabled=(
                    autonomous_agents_enabled or reasoning_plan.enabled
                ),
                completed_rounds=len(session.reasoning_state.rounds),
                **(
                    {"fixed_planned_rounds": False, **autonomous_summary}
                    if autonomous_agents_enabled
                    else {"planned_rounds": reasoning_plan.planned_rounds}
                ),
                stop_reason=reasoning_stop_reason,
                degraded_reason=reasoning_degraded_reason,
                candidate_id=(
                    primary_candidate.candidate_id
                    if primary_candidate is not None
                    else ""
                ),
            )
            shadow_candidate = (
                shadow_outcome.to_candidate(session.problem_ir.answer_type)
                if shadow_outcome is not None
                else None
            )
            trace.add(
                "shadow_probe_completed",
                enabled=self._shadow_executor is not None,
                **(
                    shadow_outcome.to_trace_dict(include_answer=True)
                    if shadow_outcome is not None
                    else {
                        "status": "disabled",
                        "capability": "",
                        "normalized_input": "",
                        "final_answer": "",
                        "public_solution_steps": [],
                        "assumptions": [],
                        "limitations": [],
                        "elapsed_seconds": 0.0,
                    }
                ),
                disclosed_after_primary=True,
                model_calls_added=0,
            )
            if shadow_candidate is not None:
                fanout.candidates.append(shadow_candidate)
                trace.add(
                    "candidate_generation_started",
                    candidate_id=shadow_candidate.candidate_id,
                    role=shadow_candidate.role,
                    planned_method_family="deterministic-shadow",
                )
                trace.add(
                    "candidate_generated",
                    **candidate_trace_payload(shadow_candidate),
                )
            bounded_candidates = []
            for candidate in fanout.candidates:
                try:
                    session.budget.record_claims(len(candidate.claims))
                except BudgetExceeded:
                    fanout.failures.append(
                        BranchFailure(
                            candidate.candidate_id,
                            "claim_budget_exhausted",
                        )
                    )
                    trace.add(
                        "candidate_evidence_completed",
                        candidate_id=candidate.candidate_id,
                        status="skipped",
                        reason="claim_budget_exhausted",
                        claim_results=[],
                        answer_shape={"status": "skipped", "strength": "none"},
                        hard_fail=False,
                        unknown_claim_ids=[
                            claim.claim_id for claim in candidate.claims
                        ],
                    )
                else:
                    bounded_candidates.append(candidate)
            fanout.candidates = bounded_candidates
            session.route_plan = replace(
                session.route_plan,
                candidate_count=max(
                    1,
                    sum(
                        candidate.source.startswith("llm_")
                        for candidate in fanout.candidates
                    ),
                ),
            )
            fanout.failures.sort(key=lambda item: item.candidate_id)
            session.candidates.extend(fanout.candidates)
            trace.add(
                "candidate_fanout_completed",
                completed=[candidate.candidate_id for candidate in fanout.candidates],
                failed=[failure.candidate_id for failure in fanout.failures],
                failures=[failure.to_dict() for failure in fanout.failures],
                contract_deviations={
                    candidate.candidate_id: list(candidate.contract_deviations)
                    for candidate in fanout.candidates
                    if candidate.contract_deviations
                },
            )
            if not fanout.candidates:
                raise RuntimeError("all solver branches failed")
            if (
                self._config.enable_peer_cross_review
                and autonomous_agents_enabled
            ):
                fanout.candidates = self._run_solver_peer_review_phase(
                    session,
                    trace,
                    fanout.candidates,
                )
                if not fanout.candidates:
                    raise RuntimeError("all independent candidates were conceded")
            if session.budget.must_finalize():
                trace.add(
                    "deadline_finalize",
                    stage="after_fanout",
                    retained_candidates=[
                        candidate.candidate_id
                        for candidate in fanout.candidates
                    ],
                    disabled=[
                        "additional_model_calls",
                        "lemma",
                        "repair",
                        "finalizer",
                    ],
                )
            self._transition(
                session,
                trace,
                RuntimePhase.CONTEXT_READY,
                RuntimePhase.CANDIDATES_READY,
                "candidate_fanout_completed",
            )
            ledger = EvidenceLedger(
                session.evidence,
                session.budget,
                fanout.candidates,
            )
            if shadow_candidate is not None:
                ledger.record_tool_result(
                    candidate_id=shadow_candidate.candidate_id,
                    claim_id=shadow_candidate.claims[0].claim_id,
                    result=shadow_outcome.to_tool_result(),
                    arguments={
                        "capability": shadow_outcome.capability,
                        "normalized_input": shadow_outcome.normalized_input,
                    },
                    assumptions=list(shadow_outcome.assumptions),
                    domains=session.problem_ir.domains,
                    duration_ms=shadow_outcome.elapsed_seconds * 1000.0,
                    timeout_seconds=min(5.0, self._config.max_tool_seconds),
                    claim_kind="equality",
                    input_complete=True,
                    context_complete=True,
                    request_status="ready",
                    schema_valid=True,
                )
            tool_results = []
            admission_rejections: dict[str, list[str]] = {}
            admitted_candidates = []
            for item in fanout.candidates:
                if (
                    item.parse_tier == "answer_recovered"
                    and not self._config.enable_tools
                ):
                    admission_rejections[item.candidate_id] = [
                        "answer_recovery_evidence_unavailable"
                    ]
                    continue
                admission = self._candidate_stage.evaluate(
                    item,
                    session.problem_ir,
                )
                if not admission.accepted:
                    admission_rejections[item.candidate_id] = (
                        admission.rejection_codes
                    )
                    continue
                if self._config.enable_tools:
                    result, _ = self._run_answer_type_check(session, item, ledger)
                    tool_results.append(
                        {
                            "candidate_id": item.candidate_id,
                            "status": result.status,
                            "request_status": "ready",
                            "schema_valid": not self._tool_executor.validate_arguments(
                                "answer_type_check",
                                {
                                    "answer": item.final_answer,
                                    "answer_type": session.problem_ir.answer_type,
                                },
                            ),
                            "outcome_reason": _tool_outcome_reason(
                                result.status,
                                result.summary,
                            ),
                        }
                    )
                    admission = self._candidate_stage.evaluate(
                        item,
                        session.problem_ir,
                        answer_shape_status=result.status,
                    )
                    if not admission.accepted:
                        admission_rejections[item.candidate_id] = (
                            admission.rejection_codes
                        )
                        continue
                if self._config.enable_tools and self._config.enable_evidence:
                    claim_records = self._evidence_stage.verify(
                        item,
                        ledger,
                        domains=session.problem_ir.domains,
                        assumptions=session.problem_ir.assumptions,
                        budget=session.budget,
                        selected_tools=session.route_plan.selected_tools,
                    )
                    tool_results.extend(
                        {
                            "candidate_id": item.candidate_id,
                            "claim_id": record.claim_id,
                            "status": record.status,
                            "request_status": record.invocation.get(
                                "request_status",
                                record.payload.get("request_status", ""),
                            ),
                            "schema_valid": bool(
                                record.invocation.get("schema_valid", False)
                            ),
                            "outcome_reason": _tool_outcome_reason(
                                record.status,
                                record.description,
                            ),
                        }
                        for record in claim_records
                    )
                admitted_candidates.append(item)
            if self._config.enable_tools:
                trace.add("tool_checks", checks=tool_results)
                if self._config.enable_memory:
                    blackboard.publish(
                        "System",
                        "evidence",
                        {
                            "evidence_ids": [
                                record.evidence_id for record in session.evidence
                            ]
                        },
                    )
            for candidate in fanout.candidates:
                evidence_checks_enabled = (
                    self._config.enable_tools
                    and self._config.enable_evidence
                )
                self._trace_candidate_evidence(
                    trace,
                    candidate,
                    [
                        record
                        for record in session.evidence
                        if record.candidate_id == candidate.candidate_id
                    ],
                    status=(
                        "rejected"
                        if candidate.candidate_id in admission_rejections
                        else (
                            "completed"
                            if evidence_checks_enabled
                            else "skipped"
                        )
                    ),
                    reason=(
                        "candidate_admission_rejected"
                        if candidate.candidate_id in admission_rejections
                        else (
                            "evidence_completed"
                            if evidence_checks_enabled
                            else "evidence_checks_disabled"
                        )
                    ),
                )
            active_candidates = admitted_candidates
            if not active_candidates:
                raise RuntimeError("all candidates failed admission")
            if not self._config.enable_evidence:
                remember_safe_candidate(active_candidates, "admitted")
            repair_triggers = {
                item.candidate_id: sorted(
                    {
                        record.claim_id or "__answer_shape__"
                        for record in session.evidence
                        if record.candidate_id == item.candidate_id
                        and is_fatal_hard_failure(record)
                    }
                )
                for item in active_candidates
            }
            repair_triggers = {
                candidate_id: claims
                for candidate_id, claims in repair_triggers.items()
                if claims
            }
            postcheck_failure_codes = tuple(
                dict.fromkeys(
                    (
                        *(
                            f"tool_{record.status}"
                            for record in session.evidence
                            if record.evidence_type.startswith("tool:")
                            and record.status in {"fail", "unknown", "error"}
                        ),
                        *(
                            str(
                                record.invocation.get(
                                    "request_status",
                                    "",
                                )
                            )
                            for record in session.evidence
                            if record.evidence_type
                            == "host:check_type_resolution"
                        ),
                    )
                )
            )
            if self._config.enable_skills and postcheck_failure_codes:
                postcheck_skills = {
                    role: self._dynamic_skills.compose_for_role(
                        session.problem_ir,
                        role=role,
                        route_skill_names=(
                            session.route_plan.selected_skills
                        ),
                        max_chars=self._config.skill_char_budget,
                        state=session.reasoning_state,
                        failure_codes=postcheck_failure_codes,
                        selection_context="candidate_tool_feedback",
                    )
                    for role in _SKILL_RUNTIME_ROLES
                }
                role_skill_contexts.update(
                    {
                        role: composition.text
                        for role, composition in postcheck_skills.items()
                    }
                )
                self._trace_dynamic_skill_selection(
                    trace,
                    postcheck_skills,
                    selection_context="candidate_tool_feedback",
                )
            lemma_eligible, lemma_reasons = self._lemma_eligibility(
                session,
                active_candidates,
            )
            optional_model_work_allowed = (
                self._provider_allows_optional_model_work()
            )
            if not optional_model_work_allowed:
                trace.add(
                    "call_allocation_rebalanced",
                    reason="provider_degraded",
                    provider_health=self._provider_health_state(),
                    disabled=["repair", "lemma", "verifier", "finalizer"],
                )
            allocation = _build_call_allocation(
                session.budget,
                max_calls=self._config.max_model_calls,
                router_calls=allocation.router,
                candidate_count=session.route_plan.candidate_count,
                verifier_required=verifier_required,
                repair_requested=(
                    self._config.enable_repair
                    and self._config.enable_evidence
                    and optional_model_work_allowed
                    and bool(repair_triggers)
                    and session.budget.deadline.exploration_allowed()
                ),
                lemma_requested=(
                    self._config.enable_lemma_loop
                    and session.route_plan.use_lemma_loop
                    and optional_model_work_allowed
                    and lemma_eligible
                ),
                finalizer_requested=(
                    self._config.enable_finalizer
                    and session.route_plan.use_llm_finalizer
                    and optional_model_work_allowed
                ),
            )
            _apply_stage_allocation(session.budget, allocation)
            session.route_plan = replace(
                session.route_plan,
                use_lemma_loop=(
                    session.route_plan.use_lemma_loop
                    and lemma_eligible
                    and optional_model_work_allowed
                    and allocation.lemma_reserve > 0
                ),
                use_llm_finalizer=(
                    session.route_plan.use_llm_finalizer
                    and optional_model_work_allowed
                    and allocation.finalizer_reserve > 0
                ),
            )
            repair_unreachable = (
                "repair" in allocation.unreachable_by_budget
                if repair_triggers
                else False
            )
            trace.add(
                "call_allocation_rebalanced",
                evidence_repair_triggers=repair_triggers,
                lemma_eligibility={
                    "eligible": lemma_eligible,
                    "reasons": lemma_reasons,
                },
                repair_unreachable_reason=(
                    "model call budget reserved for required stages"
                    if repair_unreachable
                    else ""
                ),
                **allocation.to_dict(),
            )
            if (
                self._config.enable_repair
                and self._config.enable_evidence
                and allocation.repair_reserve > 0
                and not session.budget.deadline.exploration_allowed()
            ):
                trace.add(
                    "deadline_finalize",
                    stage="before_repair",
                    disabled=["repair"],
                )
            repair_service = ClaimRepairService(max_total_repairs=1)
            repair_attempted = False
            replaced_source_candidate_ids: set[str] = set()
            if (
                self._config.enable_repair
                and self._config.enable_evidence
                and self._provider_allows_optional_model_work()
                and allocation.repair_reserve > 0
                and session.budget.deadline.exploration_allowed()
            ):
                repaired_candidates = []
                for item in active_candidates:
                    repair_result = repair_service.attempt(
                        item,
                        session.evidence,
                        repair=lambda candidate, affected, local_evidence: self._repair_candidate(
                            session,
                            blackboard,
                            trace,
                            candidate,
                            affected,
                            local_evidence,
                            role_skill_contexts.get("RepairAgent", ""),
                        ),
                        reverify=lambda candidate, affected: self._reverify_repair_candidate(
                            session,
                            candidate,
                            ledger,
                            affected,
                        ),
                    )
                    if repair_result.proposed is not None:
                        session.candidates.append(repair_result.proposed)
                        trace.add(
                            "repair_proposed",
                            source_candidate_id=item.candidate_id,
                            proposed_candidate_id=(
                                repair_result.proposed.candidate_id
                            ),
                            affected_claim_ids=repair_result.affected_claim_ids,
                            changes=self._repair_trace_changes(
                                item,
                                repair_result.proposed,
                                repair_result.changed_claim_ids,
                            ),
                            answer_changed=(
                                item.final_answer
                                != repair_result.proposed.final_answer
                            ),
                            old_final_answer=item.final_answer,
                            new_final_answer=(
                                repair_result.proposed.final_answer
                            ),
                            proposed_content=public_candidate_content(
                                repair_result.proposed
                            ),
                            content_digest=candidate_trace_payload(
                                repair_result.proposed
                            )["content_digest"],
                        )
                        self._trace_candidate_evidence(
                            trace,
                            repair_result.proposed,
                            repair_result.new_evidence,
                            status=(
                                "completed"
                                if repair_result.new_evidence
                                else "skipped"
                            ),
                            reason=repair_result.reason,
                        )
                    if repair_result.triggered:
                        repair_attempted = True
                        trace.add(
                            "repair_completed",
                            source_candidate_id=item.candidate_id,
                            **(
                                {
                                    "proposed_candidate_id": (
                                        repair_result.proposed.candidate_id
                                    )
                                }
                                if repair_result.proposed is not None
                                else {}
                            ),
                            selected_candidate_id=repair_result.selected.candidate_id,
                            affected_claim_ids=repair_result.affected_claim_ids,
                            reverified_claim_ids=sorted(
                                {
                                    record.claim_id
                                    for record in repair_result.new_evidence
                                    if record.claim_id is not None
                                }
                            ),
                            evidence_ids=[
                                record.evidence_id
                                for record in repair_result.new_evidence
                            ],
                            evidence_quality_before=(
                                "hard_fail"
                                if repair_result.triggered
                                else "unchanged"
                            ),
                            evidence_quality_after=(
                                "hard_pass"
                                if not repair_result.rolled_back
                                else "not_improved"
                            ),
                            rolled_back=repair_result.rolled_back,
                            reason=repair_result.reason,
                        )
                    repaired_candidates.append(repair_result.selected)
                    if (
                        repair_result.selected.candidate_id
                        != item.candidate_id
                    ):
                        replaced_source_candidate_ids.add(item.candidate_id)
                active_candidates = repaired_candidates
            evidence_gate = self._evidence_stage.hard_gate(
                active_candidates,
                ledger,
                enabled=self._config.enable_evidence,
            )
            viable = evidence_gate.accepted
            remember_safe_candidate(viable, "hard_evidence_passed")
            viable_candidate_ids = {
                item.candidate_id
                for item in viable
            }
            trace.add(
                "hard_evidence_gate",
                accepted=[item.candidate_id for item in viable],
                rejected=[
                    item.candidate_id
                    for item in fanout.candidates
                    if item.candidate_id not in viable_candidate_ids
                    and item.candidate_id
                    not in replaced_source_candidate_ids
                ],
            )
            if not viable:
                # A candidate that was safe before the hard-evidence gate is
                # no longer salvageable once that gate rejects every option.
                last_safe_candidate = None
                last_safe_checkpoint = ""
                raise RuntimeError("all candidates failed hard evidence")
            self._transition(
                session,
                trace,
                RuntimePhase.CANDIDATES_READY,
                RuntimePhase.EVIDENCE_READY,
                "evidence_completed" if self._config.enable_evidence else "evidence_skipped",
            )
            if self._config.enable_proof_obligations:
                for item in viable:
                    session.proof_obligations[item.candidate_id] = self._proof_stage.generate(
                        session.problem_ir,
                        item,
                        problem_obligations=session.problem_obligations,
                    )
            trace.add(
                "proof_obligations_generated",
                enabled=self._config.enable_proof_obligations,
                candidates={
                    candidate_id: [
                        obligation.to_dict() for obligation in obligations
                    ]
                    for candidate_id, obligations in session.proof_obligations.items()
                },
            )
            self._transition(
                session,
                trace,
                RuntimePhase.EVIDENCE_READY,
                RuntimePhase.OBLIGATIONS_READY,
                (
                    "obligations_generated"
                    if self._config.enable_proof_obligations
                    else "obligations_skipped"
                ),
            )
            self._transition(
                session,
                trace,
                RuntimePhase.OBLIGATIONS_READY,
                RuntimePhase.PRECHECKED,
                "pre_lemma_checks_completed",
            )
            if not session.budget.deadline.optional_work_allowed():
                session.route_plan = replace(
                    session.route_plan,
                    max_reasoning_rounds=1,
                    use_lemma_loop=False,
                    use_llm_finalizer=False,
                )
                trace.add(
                    "deadline_finalize",
                    stage="before_lemma",
                    disabled=["lemma", "finalizer"],
                )
            lemma_result = self._lemma_loop.run(
                session.route_plan,
                viable,
                session.evidence,
                session.proof_obligations,
                session.lemma_memory,
                expand_round=lambda verified, round_id: self._expand_with_verified_lemmas(
                    session,
                    blackboard,
                    trace,
                    verified,
                    round_id,
                    role_skill_contexts.get("PrimarySolver", ""),
                ),
                target=(
                    session.problem_ir.target_phrase
                    or session.problem_ir.requested_output
                ),
            )
            session.lemmas.extend(lemma_result.lemmas)
            session.rounds.extend(lemma_result.rounds)
            session.candidates.extend(lemma_result.generated_candidates)
            self._transition(
                session,
                trace,
                RuntimePhase.PRECHECKED,
                RuntimePhase.LEMMA_EXPANDED,
                lemma_result.stop_reason,
            )
            expanded_ids = {
                item.candidate_id for item in lemma_result.generated_candidates
            }
            expanded_precheck_rejections: dict[str, list[str]] = {}
            for expanded in lemma_result.generated_candidates:
                rejection_codes: list[str] = []
                ledger.register_candidate(expanded)
                try:
                    session.budget.record_claims(len(expanded.claims))
                except BudgetExceeded:
                    rejection_codes.append("claim_budget")
                admission = self._candidate_stage.evaluate(
                    expanded,
                    session.problem_ir,
                )
                rejection_codes.extend(admission.rejection_codes)
                if not rejection_codes and self._config.enable_tools:
                    answer_shape, _ = self._run_answer_type_check(
                        session,
                        expanded,
                        ledger,
                    )
                    rejection_codes.extend(
                        self._candidate_stage.evaluate(
                            expanded,
                            session.problem_ir,
                            answer_shape_status=answer_shape.status,
                        ).rejection_codes
                    )
                if (
                    not rejection_codes
                    and self._config.enable_tools
                    and self._config.enable_evidence
                ):
                    self._evidence_stage.verify(
                        expanded,
                        ledger,
                        domains=session.problem_ir.domains,
                        assumptions=session.problem_ir.assumptions,
                        budget=session.budget,
                        selected_tools=session.route_plan.selected_tools,
                    )
                    if ledger.has_hard_fail(expanded.candidate_id):
                        rejection_codes.append("claim_hard_fail")
                expanded_records = [
                    record
                    for record in session.evidence
                    if record.candidate_id == expanded.candidate_id
                ]
                self._trace_candidate_evidence(
                    trace,
                    expanded,
                    expanded_records,
                    status=(
                        "completed"
                        if expanded_records
                        else "skipped"
                    ),
                    reason=(
                        "precheck_rejected"
                        if rejection_codes
                        else (
                            "evidence_completed"
                            if expanded_records
                            else "no_supported_checks"
                        )
                    ),
                )
                if rejection_codes:
                    expanded_precheck_rejections[expanded.candidate_id] = sorted(
                        set(rejection_codes)
                    )
                    continue
                if self._config.enable_proof_obligations:
                    session.proof_obligations[expanded.candidate_id] = (
                        self._proof_stage.generate(
                            session.problem_ir,
                            expanded,
                            problem_obligations=(
                                session.problem_obligations
                            ),
                        )
                    )
                viable.append(expanded)
            remember_safe_candidate(viable, "lemma_expanded")
            if session.route_plan.risk_level == "high":
                trace.add(
                    "lemma_loop_completed",
                    rounds=len(lemma_result.rounds),
                    verified=[
                        lemma.lemma_id for lemma in lemma_result.lemmas if lemma.status == "verified"
                    ],
                    stop_reason=lemma_result.stop_reason,
                    error_rate=lemma_result.error_rate,
                    checked_count=sum(
                        lemma.status in {"verified", "rejected", "conflicted"}
                        for lemma in lemma_result.lemmas
                    ),
                    error_count=sum(
                        lemma.status in {"rejected", "conflicted"}
                        for lemma in lemma_result.lemmas
                    ),
                    generated_candidates=[
                        item.candidate_id for item in lemma_result.generated_candidates
                    ],
                    lemmas=[lemma.to_dict() for lemma in lemma_result.lemmas],
                    round_states=[
                        round_state.to_dict()
                        for round_state in lemma_result.rounds
                    ],
                    downstream_usage={
                        candidate_id: list(lemma_ids)
                        for candidate_id, lemma_ids
                        in lemma_result.expansion_dependencies.items()
                    },
                    eligibility={
                        "eligible": lemma_eligible,
                        "reasons": lemma_reasons,
                    },
                    active_skills=list(
                        skill_compositions["LemmaCurator"].included
                    )
                    if "LemmaCurator" in skill_compositions
                    else [],
                )
            required_obligations = [
                obligation
                for item in viable
                for obligation in session.proof_obligations.get(
                    item.candidate_id,
                    [],
                )
                if obligation.required
            ]
            review_summaries = [
                CandidateReviewSummary.from_candidate(item)
                for item in viable
            ]
            conflict_matrix = CandidateConflictMatrix.build(
                review_summaries,
                session.peer_reviews,
            )
            review_targets = conflict_matrix.review_targets()
            trace.add(
                "candidate_conflict_matrix",
                summaries=[
                    summary.to_dict() for summary in review_summaries
                ],
                matrix=conflict_matrix.to_dict(),
                review_targets=[
                    target.to_dict()
                    for target in review_targets
                ],
            )
            reviewable_work = has_reviewable_work(
                viable,
                session.proof_obligations,
                conflict_matrix,
            ) or self._config.enable_verification_closure
            verifier_required = (
                self._config.enable_verifier
                and self._config.enable_evidence
                and self._provider_allows_optional_model_work()
                and reviewable_work
            )
            post_verifier_repair_requested = (
                self._config.enable_repair
                and self._config.enable_evidence
                and self._provider_allows_optional_model_work()
                and verifier_required
                and not repair_attempted
                and session.budget.deadline.exploration_allowed()
            )
            if verifier_required:
                allocation = _build_call_allocation(
                    session.budget,
                    max_calls=self._config.max_model_calls,
                    router_calls=allocation.router,
                    candidate_count=session.route_plan.candidate_count,
                    verifier_required=verifier_required,
                    repair_requested=post_verifier_repair_requested,
                    lemma_requested=allocation.lemma_reserve > 0,
                    finalizer_requested=allocation.finalizer_reserve > 0,
                    reverification_requested=post_verifier_repair_requested,
                )
                _apply_stage_allocation(session.budget, allocation)
                trace.add(
                    "call_allocation_rebalanced",
                    evidence_repair_triggers={},
                    post_verifier_repair_requested=(
                        post_verifier_repair_requested
                    ),
                    **allocation.to_dict(),
                )
            skeptic_reviewed: set[str] = set()
            verifier_reason = "not_requested"
            verifier_result = None
            if (
                self._config.enable_verifier
                and self._config.enable_evidence
                and self._provider_allows_optional_model_work()
                and verifier_required
                and reviewable_work
                and session.budget.deadline.exploration_allowed()
            ):
                (
                    verifier_result,
                    verifier_reason,
                    skeptic_reviewed,
                    _,
                ) = self._run_skeptic_review(
                    session,
                    blackboard,
                    trace,
                    viable,
                    ledger,
                    role_skill_contexts.get("VerifierSkeptic", ""),
                    round_name="initial",
                )
            if (
                self._config.enable_verification_closure
                and verifier_result is not None
                and verifier_result.requires_new_branch
            ):
                new_branch = self._run_new_branch_cycle(
                    session,
                    blackboard,
                    trace,
                    viable,
                    ledger,
                    role_skill_contexts,
                )
                if new_branch is not None:
                    viable.append(new_branch)
                    required_obligations.extend(
                        item
                        for item in session.proof_obligations.get(
                            new_branch.candidate_id,
                            [],
                        )
                        if item.required
                    )
                    (
                        verifier_result,
                        verifier_reason,
                        branch_reviewed,
                        _,
                    ) = self._run_skeptic_review(
                        session,
                        blackboard,
                        trace,
                        viable,
                        ledger,
                        role_skill_contexts.get("VerifierSkeptic", ""),
                        round_name="post_new_branch",
                    )
                    skeptic_reviewed.update(branch_reviewed)
            post_repair_revalidated = False
            verifier_triggers: dict[str, list[str]] = {}
            if verifier_result is not None:
                verifier_triggers = (
                    verifier_result.actionable_claims()
                    if self._config.enable_verification_closure
                    else actionable_verifier_failures(
                        verifier_result.findings
                    )
                )
            atomic_repair_budget = session.budget.snapshot()
            repair_pair_time_reserve = stage_sequence_reserve_seconds(
                ("repair", "verifier"),
                session.budget.model_queue_budget_seconds,
            )
            repair_pair_time_available = stage_sequence_feasible(
                ("repair", "verifier"),
                remaining_seconds=(
                    session.budget.deadline.remaining_for_model_call()
                ),
                maximum_queue_seconds=(
                    session.budget.model_queue_budget_seconds
                ),
            )
            repair_pair_available = (
                atomic_repair_budget.remaining_calls >= 2
                and atomic_repair_budget.stage_remaining.get("repair", 0) >= 1
                and atomic_repair_budget.stage_remaining.get("verifier", 0) >= 1
                and atomic_repair_budget.exploration_open
                and repair_pair_time_available
            )
            trace.add(
                "repair_actionability_gate",
                actionable_claims=verifier_triggers,
                atomic_budget_pair_available=repair_pair_available,
                atomic_time_pair_available=repair_pair_time_available,
                required_pair_seconds=round(repair_pair_time_reserve, 6),
                remaining_model_seconds=round(
                    session.budget.deadline.remaining_for_model_call(),
                    6,
                ),
                budget=atomic_repair_budget.to_dict(),
            )
            if (
                post_verifier_repair_requested
                and allocation.repair_reserve > 0
                and allocation.verifier > 1
                and verifier_triggers
                and repair_pair_available
                and session.budget.deadline.exploration_allowed()
            ):
                problem_ir = session.problem_ir
                if problem_ir is None:
                    raise RuntimeError("problem IR unavailable during repair")
                for item in viable:
                    trigger_claim_ids = sorted(
                        set(verifier_triggers.get(item.candidate_id, []))
                    )
                    if not trigger_claim_ids:
                        continue
                    trigger_critique = next(
                        (
                            critique
                            for critique in reversed(session.critiques)
                            if any(
                                finding.candidate_id == item.candidate_id
                                and finding.claim_id in trigger_claim_ids
                                and finding.status == "fail"
                                and finding.actionability == "local_repair"
                                for finding in critique.findings
                            )
                        ),
                        None,
                    )
                    before_decision = self._proof_stage.evaluate(
                        item,
                        session.evidence,
                        session.proof_obligations.get(
                            item.candidate_id,
                            [],
                        ),
                    )
                    before_score = self._repair_completion_score(
                        item,
                        before_decision,
                        session.evidence,
                    )
                    affected_for_quality = set(
                        claim_impact_closure(
                            item,
                            trigger_claim_ids,
                        )
                    )
                    before_local_hard_passes = sum(
                        is_semantic_hard_pass(record)
                        and record.claim_id in affected_for_quality
                        for record in session.evidence
                        if record.candidate_id == item.candidate_id
                    )

                    def accept_post_verifier_repair(
                        proposed,
                        new_evidence,
                    ):
                        session.proof_obligations[proposed.candidate_id] = (
                            self._proof_stage.generate(
                                problem_ir,
                                proposed,
                                problem_obligations=(
                                    session.problem_obligations
                                ),
                            )
                        )
                        (
                            _,
                            rereview_reason,
                            rereviewed,
                            verifier_records,
                        ) = self._run_skeptic_review(
                            session,
                            blackboard,
                            trace,
                            [proposed],
                            ledger,
                            role_skill_contexts.get(
                                "VerifierSkeptic",
                                "",
                            ),
                            round_name="post_repair",
                        )
                        skeptic_reviewed.update(rereviewed)
                        new_evidence.extend(verifier_records)
                        if rereview_reason != "accepted":
                            return False, "post_repair_verifier_unavailable"
                        after_decision = self._proof_stage.evaluate(
                            proposed,
                            session.evidence,
                            session.proof_obligations.get(
                                proposed.candidate_id,
                                [],
                            ),
                        )
                        after_score = self._repair_completion_score(
                            proposed,
                            after_decision,
                            session.evidence,
                        )
                        after_local_hard_passes = sum(
                            is_semantic_hard_pass(record)
                            and record.claim_id in affected_for_quality
                            for record in session.evidence
                            if record.candidate_id == proposed.candidate_id
                        )
                        if after_decision.status not in {
                            "complete",
                            "model_reviewed",
                        }:
                            return False, "post_repair_proof_incomplete"
                        if after_local_hard_passes < before_local_hard_passes:
                            return False, "evidence_quality_decreased"
                        if after_score >= before_score:
                            return False, "post_repair_not_strictly_better"
                        return True, "accepted_post_verifier"

                    repair_result = repair_service.attempt_for_trigger(
                        item,
                        session.evidence,
                        trigger_claim_ids,
                        repair=lambda candidate, affected, local_evidence: self._repair_candidate(
                            session,
                            blackboard,
                            trace,
                            candidate,
                            affected,
                            local_evidence,
                            role_skill_contexts.get("RepairAgent", ""),
                        ),
                        reverify=lambda candidate, affected: self._reverify_repair_candidate(
                            session,
                            candidate,
                            ledger,
                            affected,
                        ),
                        accept=accept_post_verifier_repair,
                    )
                    repair_attempted = repair_attempted or repair_result.triggered
                    post_repair_revalidated = bool(
                        repair_result.proposed is not None
                        and repair_result.new_evidence
                    )
                    if repair_result.proposed is not None:
                        session.candidates.append(repair_result.proposed)
                        if repair_result.rolled_back:
                            for obligation in session.proof_obligations.get(
                                repair_result.proposed.candidate_id,
                                [],
                            ):
                                if obligation.required:
                                    obligation.status = "unresolved"
                                    obligation.satisfaction_evidence_ids = []
                        trace.add(
                            "repair_proposed",
                            source_candidate_id=item.candidate_id,
                            proposed_candidate_id=(
                                repair_result.proposed.candidate_id
                            ),
                            affected_claim_ids=repair_result.affected_claim_ids,
                            changes=self._repair_trace_changes(
                                item,
                                repair_result.proposed,
                                repair_result.changed_claim_ids,
                            ),
                            answer_changed=(
                                item.final_answer
                                != repair_result.proposed.final_answer
                            ),
                            old_final_answer=item.final_answer,
                            new_final_answer=(
                                repair_result.proposed.final_answer
                            ),
                            proposed_content=public_candidate_content(
                                repair_result.proposed
                            ),
                            content_digest=candidate_trace_payload(
                                repair_result.proposed
                            )["content_digest"],
                            repair_stage="post_verifier",
                        )
                    if repair_result.triggered:
                        session.repair_lineage.append(
                            {
                                "source_candidate_id": item.candidate_id,
                                "proposed_candidate_id": (
                                    repair_result.proposed.candidate_id
                                    if repair_result.proposed is not None
                                    else ""
                                ),
                                "critique_id": (
                                    trigger_critique.critique_id
                                    if trigger_critique is not None
                                    else ""
                                ),
                                "critique_artifact_id": (
                                    trigger_critique.artifact_id
                                    if trigger_critique is not None
                                    else ""
                                ),
                                "repair_artifact_id": next(
                                    (
                                        artifact["artifact_id"]
                                        for artifact in reversed(
                                            session.agent_runtime.artifacts.snapshot()
                                        )
                                        if artifact["artifact_type"]
                                        == "RepairPatchArtifact"
                                    ),
                                    "",
                                ),
                                "affected_claim_ids": list(
                                    repair_result.affected_claim_ids
                                ),
                                "rolled_back": repair_result.rolled_back,
                                "reason": repair_result.reason,
                                "reverified": bool(repair_result.new_evidence),
                            }
                        )
                        trace.add(
                            "repair_completed",
                            source_candidate_id=item.candidate_id,
                            **(
                                {
                                    "proposed_candidate_id": (
                                        repair_result.proposed.candidate_id
                                    )
                                }
                                if repair_result.proposed is not None
                                else {}
                            ),
                            selected_candidate_id=(
                                repair_result.selected.candidate_id
                            ),
                            affected_claim_ids=repair_result.affected_claim_ids,
                            reverified_claim_ids=sorted(
                                {
                                    record.claim_id
                                    for record in repair_result.new_evidence
                                    if record.claim_id is not None
                                }
                            ),
                            evidence_ids=[
                                record.evidence_id
                                for record in repair_result.new_evidence
                            ],
                            evidence_quality_before=str(before_score),
                            evidence_quality_after=repair_result.reason,
                            rolled_back=repair_result.rolled_back,
                            reason=repair_result.reason,
                            repair_stage="post_verifier",
                            critique_id=(
                                trigger_critique.critique_id
                                if trigger_critique is not None
                                else ""
                            ),
                            critique_artifact_id=(
                                trigger_critique.artifact_id
                                if trigger_critique is not None
                                else ""
                            ),
                            repair_artifact_id=(
                                session.repair_lineage[-1].get(
                                    "repair_artifact_id",
                                    "",
                                )
                                if session.repair_lineage
                                else ""
                            ),
                        )
                    viable = [
                        (
                            repair_result.selected
                            if candidate.candidate_id == item.candidate_id
                            else candidate
                        )
                        for candidate in viable
                    ]
                    break
            completion_status_by_id = {
                item.candidate_id: "not_required"
                for item in viable
            }
            if (
                self._config.enable_proof_obligations
                and required_obligations
            ):
                completion_decisions = [
                    self._proof_stage.evaluate(
                        item,
                        session.evidence,
                        session.proof_obligations.get(item.candidate_id, []),
                    )
                    for item in viable
                ]
                completed_ids = {
                    decision.candidate_id
                    for decision in completion_decisions
                    if decision.status == "complete"
                }
                hard_failed_ids = {
                    decision.candidate_id
                    for decision in completion_decisions
                    if decision.status == "failed"
                }
                unreviewed_expanded_ids = (
                    expanded_ids - skeptic_reviewed
                    if verifier_required
                    else set()
                )
                retained_ids = {
                    decision.candidate_id
                    for decision in completion_decisions
                    if (
                        decision.status != "failed"
                        and decision.candidate_id not in unreviewed_expanded_ids
                    )
                }
                completion_status_by_id = {
                    decision.candidate_id: decision.status
                    for decision in completion_decisions
                }
                trace.add(
                    "proof_completion_gate",
                    accepted=sorted(retained_ids),
                    fully_verified=sorted(completed_ids),
                    degraded_accepted=sorted(
                        retained_ids - completed_ids
                    ),
                    mode="best_available",
                    verifier_reason=verifier_reason,
                    decisions=[
                        {
                            **decision.to_dict(),
                            "obligations": [
                                obligation.to_dict()
                                for obligation in session.proof_obligations.get(
                                    decision.candidate_id,
                                    [],
                                )
                            ],
                        }
                        for decision in completion_decisions
                    ],
                    rejected=[
                        {
                            "candidate_id": decision.candidate_id,
                            "status": decision.status,
                            "gate_reason": (
                                "hard_failure"
                                if decision.candidate_id in hard_failed_ids
                                else "expanded_candidate_not_skeptic_reviewed"
                            ),
                            "unresolved_obligation_ids": decision.unresolved_obligation_ids,
                            "failed_obligation_ids": decision.failed_obligation_ids,
                            "failed_claim_ids": decision.failed_claim_ids,
                        }
                        for decision in completion_decisions
                        if (
                            decision.candidate_id in hard_failed_ids
                            or decision.candidate_id in unreviewed_expanded_ids
                        )
                    ],
                )
                viable = [
                    item
                    for item in viable
                    if item.candidate_id in retained_ids
                ]
            if self._config.enable_verification_closure and viable:
                viable = self._run_final_audit_phase(
                    session,
                    blackboard,
                    trace,
                    viable,
                    ledger,
                    role_skill_contexts.get("VerifierSkeptic", ""),
                )
            self._transition(
                session,
                trace,
                RuntimePhase.LEMMA_EXPANDED,
                RuntimePhase.VERIFIED,
                "verification_and_completion_finished",
            )
            arbitration_source_phase = RuntimePhase.VERIFIED
            if post_repair_revalidated:
                self._transition(
                    session,
                    trace,
                    RuntimePhase.VERIFIED,
                    RuntimePhase.REVERIFIED,
                    "post_verifier_repair_revalidated",
                )
                arbitration_source_phase = RuntimePhase.REVERIFIED
            candidate_precheck_rejections = dict(admission_rejections)
            candidate_precheck_rejections.update(
                expanded_precheck_rejections
            )
            accepted_expanded = sorted(
                item.candidate_id
                for item in viable
                if item.candidate_id in expanded_ids
            )
            trace.add(
                "expanded_candidates_reverified",
                accepted=accepted_expanded,
                rejected=sorted(expanded_ids - set(accepted_expanded)),
                skeptic_reviewed=sorted(skeptic_reviewed.intersection(expanded_ids)),
                precheck_rejections=expanded_precheck_rejections,
                verification_chain={
                    expanded_id: {
                        "schema_validated": (
                            "candidate_schema_invalid"
                            not in expanded_precheck_rejections.get(expanded_id, [])
                        ),
                        "answer_validated": not any(
                            code == "empty_answer"
                            or code == "incompatible_answer_type"
                            or code.startswith("invalid_")
                            for code in expanded_precheck_rejections.get(
                                expanded_id,
                                [],
                            )
                        ),
                        "answer_shape_checked": self._config.enable_tools,
                        "claims_reverified": (
                            self._config.enable_tools
                            and self._config.enable_evidence
                        ),
                        "obligations_regenerated": (
                            expanded_id in session.proof_obligations
                        ),
                        "skeptic_reviewed": expanded_id in skeptic_reviewed,
                        "final_status": (
                            "accepted"
                            if expanded_id in accepted_expanded
                            else "rejected"
                        ),
                    }
                    for expanded_id in sorted(expanded_ids)
                },
            )
            if not viable:
                # Proof/evidence completion can invalidate a previously safe
                # checkpoint.  Do not return a candidate after all current
                # candidates have acquired hard failures.
                last_safe_candidate = None
                last_safe_checkpoint = ""
                raise RuntimeError("all proof candidates have hard failures")
            remember_safe_candidate(viable, "pre_arbitration")
            if len(viable) == 1:
                candidate = viable[0]
                ranking = [candidate.candidate_id]
                single_coverage = (
                    1.0
                    if completion_status_by_id.get(
                        candidate.candidate_id,
                        "not_required",
                    )
                    in {"complete", "not_required"}
                    else 0.0
                )
                single_status = completion_status_by_id.get(
                    candidate.candidate_id,
                    "not_required",
                )
                single_tier = {
                    "complete": "hard_evidence",
                    "model_reviewed": "model_review",
                    "not_required": "not_required",
                }.get(single_status, "incomplete")
                single_tier_rank = {
                    "hard_evidence": 0,
                    "independent_corroboration": 1,
                    "model_review": 2,
                    "not_required": 3,
                    "incomplete": 4,
                }[single_tier]
                single_review_support = sum(
                    1
                    if record.status == "pass"
                    else -1
                    if record.status == "fail"
                    else 0
                    for record in session.evidence
                    if record.candidate_id == candidate.candidate_id
                    and record.evidence_type
                    == "llm:VerifierSkeptic"
                    and record.payload.get("review_target_ids")
                )
                single_digest = semantic_fingerprint(
                    public_candidate_content(candidate)
                )
                rank_details = [
                    {
                        "candidate_id": candidate.candidate_id,
                        "hard_fail_count": 0,
                        "required_coverage": single_coverage,
                        "answer_consistency": 1,
                        "independent_agreement": 0,
                        "evidence_tier": single_tier,
                        "review_support": single_review_support,
                        "soft_score": 0,
                        "deterministic_tie_break": single_digest,
                        "substantive_key": [
                            0,
                            single_tier_rank,
                            -single_coverage,
                            -1,
                            0,
                            -single_review_support,
                            0,
                        ],
                        "lexicographic_key": [
                            0,
                            single_tier_rank,
                            -single_coverage,
                            -1,
                            0,
                            -single_review_support,
                            0,
                            single_digest,
                        ],
                    }
                ]
                equivalence_clusters = [[candidate.candidate_id]]
                equivalence_unknown_pairs = []
                equivalence_disagreement_pairs = []
                used_llm_arbiter = False
                tie_break_reason = "single_candidate"
                selection_mode = "single_candidate_deterministic"
            else:
                arbitration = self._arbitration.select(
                    viable,
                    session.evidence,
                    session.proof_obligations,
                    budget=session.budget,
                    problem=session.problem_ir,
                )
                candidate = arbitration.selected
                ranking = [
                    rank.candidate_id for rank in arbitration.ranks
                ]
                rank_details = [
                    rank.to_dict() for rank in arbitration.ranks
                ]
                equivalence_clusters = arbitration.clusters
                equivalence_unknown_pairs = arbitration.unknown_pairs
                equivalence_disagreement_pairs = (
                    arbitration.disagreement_pairs
                )
                used_llm_arbiter = arbitration.used_llm_arbiter
                tie_break_reason = arbitration.tie_break_reason
                selection_mode = "multi_candidate_arbitration"
            selection_reason = (
                "prefer hard evidence, independent corroboration, and "
                "targeted model review in that order; exact substantive "
                "ties use a stable public-content digest"
            )
            trace.add(
                "candidate_arbitrated",
                selected=candidate.candidate_id,
                ranking=ranking,
                rank_details=rank_details,
                viable_candidates=[item.candidate_id for item in viable],
                rejected_candidates=self._arbitration_rejections(
                    session,
                    viable,
                    candidate_precheck_rejections,
                ),
                selection_reason=selection_reason,
                tie_break_reason=tie_break_reason,
                selected_verification_status=completion_status_by_id.get(
                    candidate.candidate_id,
                    "not_required",
                ),
                selected_source=candidate.source,
                selection_quality=(
                    "degraded_shadow_only"
                    if candidate.source == "deterministic_shadow"
                    and not any(
                        item.source.startswith("llm_")
                        for item in viable
                    )
                    else "standard"
                ),
                selection_mode=selection_mode,
                equivalence_clusters=equivalence_clusters,
                equivalence_unknown_pairs=equivalence_unknown_pairs,
                equivalence_disagreement_pairs=equivalence_disagreement_pairs,
                used_llm_arbiter=used_llm_arbiter,
            )
            if self._config.enable_verification_closure:
                matching_audit = next(
                    (
                        item
                        for item in reversed(session.audits)
                        if item.candidate_id == candidate.candidate_id
                    ),
                    None,
                )
                try:
                    decision_artifact = (
                        session.agent_runtime.publish_deterministic_decision(
                            candidate_id=candidate.candidate_id,
                            candidate_version=candidate.version,
                            selection_mode=selection_mode,
                            selection_reason=selection_reason,
                            audit_artifact_id=(
                                matching_audit.artifact_id
                                if matching_audit is not None
                                else ""
                            ),
                        )
                    )
                    trace.add(
                        "decision_committed",
                        status="committed",
                        selected_candidate_id=candidate.candidate_id,
                        candidate_version=candidate.version,
                        decision_artifact_id=decision_artifact["artifact_id"],
                        audit_artifact_id=(
                            matching_audit.artifact_id
                            if matching_audit is not None
                            else ""
                        ),
                        authority="deterministic_host_arbitration",
                    )
                except (KeyError, ValueError):
                    trace.add(
                        "decision_committed",
                        status="unavailable",
                        selected_candidate_id=candidate.candidate_id,
                        candidate_version=candidate.version,
                        decision_artifact_id="",
                        audit_artifact_id="",
                        authority="deterministic_host_arbitration",
                    )
            selected_candidate_id = candidate.candidate_id
            remember_safe_candidate([candidate], "arbitrated")
            candidate_states = self._candidate_final_states(
                session,
                viable,
                selected_candidate_id,
                fanout.failures,
                candidate_precheck_rejections,
            )
            trace.add(
                "candidate_final_states",
                candidates=candidate_states,
            )
            self._transition(
                session,
                trace,
                arbitration_source_phase,
                RuntimePhase.ARBITRATED,
                "candidate_selected",
            )
            selected_admission = self._candidate_stage.evaluate(
                candidate,
                session.problem_ir,
            )
            if not selected_admission.accepted:
                # A final admission rejection is a new hard safety signal,
                # so the earlier arbitration checkpoint cannot be salvaged.
                last_safe_candidate = None
                last_safe_checkpoint = ""
                raise RuntimeError("selected candidate failed admission")
            validation_errors = self._answer_validator.validate(
                candidate,
                session.problem_ir,
            )
            trace.add(
                "primary_completed",
                model_calls=session.budget.used_calls,
                estimated_tokens=session.budget.used_tokens,
            )
            validation_warnings = sorted(
                set(
                    [
                        *selected_admission.warning_codes,
                        *validation_errors,
                    ]
                )
            )
            if validation_warnings:
                trace.add(
                    "answer_validation_warning",
                    codes=validation_warnings,
                    answer_type_confidence=(
                        session.problem_ir.answer_type_confidence
                    ),
                )
            deterministic_response = self._formatter.format(
                candidate,
                session.problem_ir,
            )
            if not deterministic_response.strip():
                raise ValueError("empty formatted response")
            final_response = deterministic_response
            self._transition(
                session,
                trace,
                RuntimePhase.ARBITRATED,
                RuntimePhase.FORMATTED,
                "deterministic_format_completed",
            )
            if (
                self._config.enable_finalizer
                and session.route_plan.use_llm_finalizer
                and self._provider_allows_optional_model_work()
                and session.budget.deadline.optional_work_allowed()
            ):
                try:
                    finalizer_context = self._build_role_context(
                        session,
                        blackboard,
                        trace,
                        role="LLMFinalizer",
                        candidates=[candidate],
                        final_answer=candidate.final_answer,
                    )
                except ContextBudgetExceeded:
                    trace.add(
                        "finalization_completed",
                        used_llm=False,
                        reason="context_budget_infeasible",
                    )
                else:
                    finalizer = self._finalizer
                    if finalizer is None:
                        raise RuntimeError("enabled finalizer was not constructed")
                    finalization = finalizer.finalize(
                        session.problem_ir,
                        candidate,
                        final_response,
                        session.budget,
                        max_tokens=self._config.primary_max_tokens,
                        context_view=finalizer_context,
                        skill_context=role_skill_contexts.get(
                            "LLMFinalizer",
                            "",
                        ),
                    )
                    final_response = (
                        finalization.text
                        if finalization.text.strip()
                        else deterministic_response
                    )
                    trace.add(
                        "finalization_completed",
                        used_llm=(
                            finalization.used_llm
                            and bool(finalization.text.strip())
                        ),
                        reason=(
                            finalization.reason
                            if finalization.text.strip()
                            else "finalizer_empty"
                        ),
                    )
            elif (
                self._config.enable_finalizer
                and session.route_plan.use_llm_finalizer
            ):
                trace.add(
                    "finalization_completed",
                    used_llm=False,
                    reason=(
                        "provider_degraded"
                        if not self._provider_allows_optional_model_work()
                        else "soft_deadline"
                    ),
                )
            final_response, final_count = self._validated_final_response(
                final_response,
                exact_answer=candidate.final_answer,
                answer_type=candidate.answer_type,
                response_mode=session.problem_ir.response_mode,
            )
            trace.add(
                "final_answer_selected",
                candidate_id=candidate.candidate_id,
                selection_reason=(
                    "selected as the best available non-disproved candidate by "
                    "verification status and lexicographic evidence arbitration"
                ),
                verification_status=completion_status_by_id.get(
                    candidate.candidate_id,
                    "not_required",
                ),
                selected_source=candidate.source,
                selection_quality=(
                    "degraded_shadow_only"
                    if candidate.source == "deterministic_shadow"
                    and not any(
                        item.source.startswith("llm_")
                        for item in viable
                    )
                    else "standard"
                ),
                public_solution={
                    "solution_text": candidate.solution_text,
                    "public_solution_steps": list(
                        candidate.public_solution_steps
                    ),
                    "final_answer": candidate.final_answer,
                    "final_response": final_response,
                },
                answer_validation={
                    "status": "pass" if not validation_errors else "warning",
                    "codes": list(validation_errors),
                },
            )
            session.budget.record_final_response(
                final_count.tokens,
                final_count.counting_mode,
            )
            self._transition(
                session,
                trace,
                RuntimePhase.FORMATTED,
                RuntimePhase.FINALIZED,
                (
                    "llm_finalizer_considered"
                    if self._config.enable_finalizer
                    else "llm_finalizer_disabled"
                ),
            )
            self._transition(
                session,
                trace,
                RuntimePhase.FINALIZED,
                RuntimePhase.COMPLETED,
                "solve_completed",
            )
            outcome = "primary"
        except Exception as error:  # The public contract requires a result on every path.
            failure = error
            caught_error = error
            failed_phase = session.phase
            error_code = terminalizer.safe(
                "failure_classification",
                lambda: classify_failure(caught_error, failed_phase).value,
                "all_candidates_failed",
            )
            transition = terminalizer.safe(
                "failure_transition",
                lambda: session.transition(
                    failed_phase,
                    RuntimePhase.FAILED,
                    reason=error_code,
                ),
                None,
            )
            if transition is not None:
                transition_payload = transition
                terminalizer.safe(
                    "failure_transition_trace",
                    lambda: trace.add(
                        "phase_transition",
                        **transition_payload,
                    ),
                    None,
                )
            if last_safe_candidate is not None:
                if any(
                    record.candidate_id == last_safe_candidate.candidate_id
                    and is_fatal_hard_failure(record)
                    for record in session.evidence
                ):
                    last_safe_candidate = None
                    last_safe_checkpoint = ""
            if last_safe_candidate is not None:
                selected_candidate_id = last_safe_candidate.candidate_id
                error_code = "degraded_candidate_salvage"
                outcome = "primary"
                final_response = terminalizer.safe(
                    "salvaged_candidate_response",
                    lambda: self._validated_final_response(
                        self._formatter.format(
                            last_safe_candidate,
                            session.problem_ir,
                        ),
                        exact_answer=last_safe_candidate.final_answer,
                        answer_type=last_safe_candidate.answer_type,
                        response_mode=session.problem_ir.response_mode,
                    )[0],
                    last_safe_candidate.final_answer,
                )
                candidate_states = terminalizer.safe(
                    "salvaged_candidate_states",
                    lambda: self._candidate_final_states(
                        session,
                        [last_safe_candidate],
                        selected_candidate_id,
                        [],
                        {},
                    ),
                    [],
                )
                transition = terminalizer.safe(
                    "salvage_transition",
                    lambda: session.transition(
                        RuntimePhase.FAILED,
                        RuntimePhase.COMPLETED,
                        reason="candidate_salvaged",
                    ),
                    None,
                )
                if transition is not None:
                    transition_payload = transition
                    terminalizer.safe(
                        "salvage_transition_trace",
                        lambda: trace.add(
                            "phase_transition",
                            **transition_payload,
                        ),
                        None,
                    )
                terminalizer.safe(
                    "salvaged_candidate_trace",
                    lambda: trace.add(
                        "candidate_salvaged",
                        candidate_id=selected_candidate_id,
                        checkpoint=last_safe_checkpoint,
                        reason="downstream_failure_preserved_unrefuted_candidate",
                        error_code=error_code,
                        public_solution={
                            "public_solution_steps": list(
                                last_safe_candidate.public_solution_steps
                            ),
                            "final_answer": last_safe_candidate.final_answer,
                        },
                    ),
                    None,
                )
                existing_events = {
                    str(event.get("event", ""))
                    for event in trace.internal_events
                    if isinstance(event, dict)
                }
                if "hard_evidence_gate" not in existing_events:
                    terminalizer.safe(
                        "salvaged_hard_evidence_trace",
                        lambda: trace.add(
                            "hard_evidence_gate",
                            accepted=[selected_candidate_id],
                            rejected=[],
                            salvage=True,
                        ),
                        None,
                    )
                if "candidate_arbitrated" not in existing_events:
                    terminalizer.safe(
                        "salvaged_arbitration_trace",
                        lambda: trace.add(
                            "candidate_arbitrated",
                            selected=selected_candidate_id,
                            ranking=[selected_candidate_id],
                            viable_candidates=[selected_candidate_id],
                            rejected_candidates=[],
                            selection_mode="degraded_candidate_salvage",
                            selected_verification_status="best_available",
                        ),
                        None,
                    )
                if "final_answer_selected" not in existing_events:
                    terminalizer.safe(
                        "salvaged_final_answer_trace",
                        lambda: trace.add(
                            "final_answer_selected",
                            candidate_id=selected_candidate_id,
                            selection_reason=(
                                "last safe candidate retained after downstream "
                                "failure"
                            ),
                            verification_status="best_available",
                            selected_source=last_safe_candidate.source,
                            selection_quality="degraded_candidate_salvage",
                            public_solution={
                                "solution_text": last_safe_candidate.solution_text,
                                "public_solution_steps": list(
                                    last_safe_candidate.public_solution_steps
                                ),
                                "final_answer": last_safe_candidate.final_answer,
                                "final_response": final_response,
                            },
                            answer_validation={
                                "status": "warning",
                                "codes": ["degraded_candidate_salvage"],
                            },
                        ),
                        None,
                    )
            else:
                final_response = terminalizer.safe(
                    "fallback_response",
                    lambda: self._fallback.solve(normalized_problem),
                    MINIMAL_FALLBACK_RESPONSE,
                )
                transition = terminalizer.safe(
                    "fallback_transition",
                    lambda: session.transition(
                        RuntimePhase.FAILED,
                        RuntimePhase.FALLBACK_COMPLETED,
                        reason="fallback_completed",
                    ),
                    None,
                )
                if transition is not None:
                    transition_payload = transition
                    terminalizer.safe(
                        "fallback_transition_trace",
                        lambda: trace.add(
                            "phase_transition",
                            **transition_payload,
                        ),
                        None,
                    )
                terminalizer.safe(
                    "fallback_trace",
                    lambda: trace.add(
                        "fallback_used",
                        reason=error_code,
                        error_code=error_code,
                        failed_phase=failed_phase.value,
                    ),
                    None,
                )

        problem_memo.clear()
        protocol_snapshot: dict[str, Any] = terminalizer.safe(
            "agent_protocol_finalize",
            lambda: session.agent_runtime.finalize(
                session.budget.model_call_records
            ),
            {
                "schema_version": "1.0",
                "mode": "hybrid_router_authoritative",
                "selection_authority": (
                    "authoritative_router_plan_then_legacy_candidate_flow"
                ),
                "active_plan_id": "",
                "counts": {},
                "call_turn_count_match": False,
                "agents": [],
                "tasks": [],
                "artifacts": [],
                "messages": [],
                "threads": [],
                "turn_lineage": [],
            },
        )
        terminalizer.safe(
            "agent_protocol_trace",
            lambda: trace.add(
                "agent_protocol",
                protocol_schema_version=protocol_snapshot.get(
                    "schema_version",
                    "1.0",
                ),
                **{
                    key: value
                    for key, value in protocol_snapshot.items()
                    if key != "schema_version"
                },
            ),
            None,
        )
        terminalizer.safe(
            "session_freeze",
            session.freeze,
            None,
        )
        terminalizer.safe(
            "close_trace_invariants",
            lambda: self._close_trace_invariants(trace),
            None,
        )
        empty_graph: dict[str, Any] = {
            "schema_version": "1.0",
            "selected_candidate_id": selected_candidate_id,
            "nodes": [],
            "edges": [],
            "summary": {
                "node_counts": {},
                "evidence_status_counts": {},
                "unresolved_required_obligations": 0,
            },
        }
        proof_graph: dict[str, Any] = terminalizer.safe(
            "proof_graph",
            lambda: build_claim_evidence_graph(
                session.candidates,
                session.evidence,
                session.proof_obligations,
                candidate_states=candidate_states,
                selected_candidate_id=selected_candidate_id,
            ),
            empty_graph,
        )
        terminalizer.safe(
            "proof_graph_trace",
            lambda: trace.add("proof_graph_completed", graph=proof_graph),
            None,
        )
        empty_transport: dict[str, Any] = {"calls": [], "summary": {}}
        transport: dict[str, Any] = terminalizer.safe(
            "transport_summary",
            lambda: build_transport_summary(session.budget.model_call_records),
            empty_transport,
        )
        terminalizer.safe(
            "transport_trace",
            lambda: trace.add("model_transport_completed", **transport),
            None,
        )
        empty_case_summary: dict[str, Any] = {
            "schema_version": "1.0",
            "outcome": outcome,
            "selected_candidate_id": selected_candidate_id,
        }
        case_summary: dict[str, Any] = terminalizer.safe(
            "case_summary",
            lambda: build_case_trace_summary(
                candidates=session.candidates,
                evidence=session.evidence,
                candidate_states=candidate_states,
                internal_events=trace.internal_events,
                model_call_records=session.budget.model_call_records,
                selected_candidate_id=selected_candidate_id,
                proof_graph_summary=proof_graph["summary"],
                outcome=outcome,
            ),
            empty_case_summary,
        )
        empty_stream_stats: dict[str, int] = {}
        case_summary["trace_streams"] = terminalizer.safe(
            "trace_stream_stats",
            lambda: trace.stream_stats,
            empty_stream_stats,
        )
        terminalizer.safe(
            "case_summary_trace",
            lambda: trace.add("case_trace_summary", summary=case_summary),
            None,
        )
        final_count = terminalizer.safe(
            "final_token_count",
            lambda: self._context_budget.ensure_text_within_window(
                final_response
            ),
            None,
        )
        if final_count is not None:
            terminalizer.safe(
                "final_token_record",
                lambda: session.budget.record_final_response(
                    final_count.tokens,
                    final_count.counting_mode,
                ),
                None,
            )
        empty_background_tail: dict[str, int] = {}
        background_tail: dict[str, int] = terminalizer.safe(
            "background_tail_summary",
            lambda: session.budget.background_tail_snapshot(),
            empty_background_tail,
        )
        terminalizer.safe(
            "background_tail_trace",
            lambda: trace.add(
                "background_tail_audit",
                **background_tail,
                note=(
                    "timed-out provider threads cannot mutate the returned result"
                ),
            ),
            None,
        )
        empty_budget_summary: dict[str, Any] = {}
        budget_summary: dict[str, Any] = terminalizer.safe(
            "budget_summary",
            lambda: session.budget.to_dict(),
            empty_budget_summary,
        )
        health_summary = terminalizer.safe(
            "closed_loop_health",
            lambda: build_closed_loop_health(
                trace.internal_events,
                budget=budget_summary,
                selected_candidate_id=selected_candidate_id,
                outcome=outcome,
                error_code=error_code,
            ),
            minimal_closed_loop_health(
                health=(
                    "timeout"
                    if outcome == "timeout"
                    else "failed"
                    if outcome != "primary"
                    else "degraded"
                ),
                root_failure_code=error_code,
            ),
        )
        terminalizer.safe(
            "closed_loop_health_trace",
            lambda: trace.add("closed_loop_health", **health_summary),
            None,
        )
        terminalizer.safe(
            "budget_summary_trace",
            lambda: trace.add(
                "budget_summary",
                **budget_summary,
                outcome=outcome,
            ),
            None,
        )
        terminalizer.safe(
            "run_completed_trace",
            lambda: trace.add(
                "run_completed",
                outcome=outcome,
                error_code=error_code,
                final_phase=session.phase.value,
            ),
            None,
        )
        terminalizer.safe(
            "budget_freeze",
            session.budget.freeze,
            None,
        )
        terminalizer.safe(
            "trace_freeze",
            trace.freeze,
            None,
        )
        metrics = terminalizer.safe(
            "run_metrics",
            lambda: collect_run_metrics(
                budget=session.budget,
                internal_events=trace.internal_events,
                session_id=session.session_id,
                request_fingerprint=run_fingerprint,
                outcome=outcome,
                final_phase=session.phase.value,
                error_code=error_code,
            ).to_dict(),
            minimal_fallback_metrics(),
        )
        if failure is not None and self._debug_sink is not None:
            debug_sink = self._debug_sink
            terminalizer.safe(
                "debug_sink",
                lambda: debug_sink.record(
                    sanitized_failure_record(
                        failure,
                        session_id=session.session_id,
                        phase=failed_phase.value,
                        error_code=error_code,
                        internal_events=trace.internal_events,
                    )
                ),
                None,
            )
        result = terminalizer.build_result(
            final_response=final_response,
            trace_factory=lambda: trace.build(final_response=final_response),
            metrics_factory=lambda: metrics,
            provenance=terminalizer.safe(
                "provenance",
                lambda: self._run_provenance.to_dict(),
                {},
            ),
            outcome=outcome,
            final_phase=session.phase.value,
            error_code=error_code,
        )
        result["_public_output_limits"] = {
            "final_response_max_chars": self._config.final_response_max_chars,
            "public_result_max_bytes": self._config.public_result_max_bytes,
            "judge_trace_max_events": self._config.judge_trace_max_events,
            "judge_trace_max_chars": self._config.judge_trace_max_chars,
            "judge_trace_event_max_chars": (
                self._config.judge_trace_event_max_chars
            ),
            "candidate_summary_max_count": (
                self._config.candidate_summary_max_count
            ),
        }
        terminalizer.safe(
            "agent_runtime_release",
            session.agent_runtime.release,
            None,
        )
        terminalizer.safe(
            "agent_runtime_unbind",
            session.budget.release_agent_runtime,
            None,
        )
        return result

    def _run_autonomous_solver_fanout(
        self,
        session,
        trace: TraceBuilder,
        *,
        role_skill_contexts: dict[str, str],
        solver_contexts: dict[str, Any],
    ) -> tuple[FanoutResult, ReasoningState, dict[str, Any]]:
        tracker = AgentProgressTracker()
        shared_lemma_context = self._run_initial_llm_lemma_curator(
            session,
            trace,
        )
        methods = list(dict.fromkeys(session.route_plan.method_families))
        methods.extend(
            method
            for method in method_families_for(
                session.route_plan.primary_subject,
                session.route_plan.problem_type,
            )
            if method not in methods
        )
        methods.extend(
            method
            for method in method_families_for(
                "general-math",
                session.route_plan.problem_type,
            )
            if method not in methods
        )
        target_count = 2 if self._config.enable_alternatives else 1
        if len(methods) < target_count:
            methods.append("independent-direct-check")
        branches = [
            _AutonomousBranch(
                role="PrimarySolver",
                candidate_id="primary-1",
                solver=PrimarySolver(self._contracts),
                method_family=methods[0],
                forbidden_method_families=tuple(methods[1:target_count]),
                context_view=solver_contexts.get("PrimarySolver"),
                skill_context=(
                    role_skill_contexts.get("PrimarySolver", "")
                    + shared_lemma_context
                ),
                state=ReasoningState.initialize(
                    session.problem_ir,
                    strategy=methods[0],
                ),
            )
        ]
        if target_count > 1:
            branches.append(
                _AutonomousBranch(
                    role="AlternativeSolver",
                    candidate_id="alternative-1",
                    solver=AlternativeSolver(self._contracts),
                    method_family=methods[1],
                    forbidden_method_families=tuple(
                        method for method in methods[:target_count] if method != methods[1]
                    ),
                    context_view=solver_contexts.get("AlternativeSolver"),
                    skill_context=(
                        role_skill_contexts.get("AlternativeSolver", "")
                        + shared_lemma_context
                    ),
                    state=ReasoningState.initialize(
                        session.problem_ir,
                        strategy=methods[1],
                    ),
                )
            )

        action_turns = 0
        progress_turns = 0
        stall_stops = 0
        while any(branch.status == "exploring" for branch in branches):
            cycle_advanced = False
            for branch in branches:
                if branch.status != "exploring":
                    continue
                pending_candidates = sum(
                    item.status not in {"abstained", "candidate_published"}
                    for item in branches
                )
                candidate_kind = (
                    "solver_candidate_proof"
                    if session.problem_ir.response_mode == "proof_full"
                    else "solver_candidate_standard"
                )
                if (
                    not session.budget.can_start_exploration()
                    or not stage_sequence_feasible(
                        [candidate_kind] * max(1, pending_candidates),
                        remaining_seconds=(
                            session.budget.snapshot().remaining_seconds
                        ),
                        maximum_queue_seconds=(
                            self._config.model_queue_budget_seconds
                        ),
                    )
                ):
                    branch.status = "ready_to_synthesize"
                    branch.stop_reason = "resource_governor_requested_synthesis"
                    continue
                try:
                    compressed = self._compress_reasoning_state(
                        branch.state,
                        trace,
                    )
                    turn = self._solver_executor.execute_autonomous_progress(
                        branch.solver,
                        SolverRequest(
                            branch.candidate_id,
                            session.problem_ir,
                            session.route_plan,
                            branch.skill_context
                            + self._autonomous_budget_context(
                                session.budget.snapshot()
                            ),
                            branch.method_family,
                            branch.forbidden_method_families,
                            branch.context_view,
                            compressed.prompt_json,
                        ),
                        session.budget,
                        mode=branch.mode,
                        temperature=(
                            self._config.primary_temperature
                            if branch.role == "PrimarySolver"
                            else max(self._config.primary_temperature, 0.35)
                        ),
                        max_tokens=self._config.primary_max_tokens,
                        optional=branch.mode == "continue",
                    )
                except Exception as error:
                    branch.status = "ready_to_synthesize"
                    branch.stop_reason = self._reasoning_failure_code(error)
                    trace.add(
                        "autonomous_turn_failed",
                        agent_role=branch.role,
                        candidate_id=branch.candidate_id,
                        mode=branch.mode,
                        failure_code=branch.stop_reason,
                        next_action="synthesize_candidate",
                    )
                    continue
                action_turns += 1
                progress_turns += 1
                cycle_advanced = True
                decision = tracker.observe(
                    f"{branch.role}:{branch.candidate_id}",
                    turn.parsed.payload,
                )
                summary: dict[str, Any] = {
                    "information_gain": decision.information_gain,
                    "added_claim_ids": [],
                    "evidence_ids": [],
                }
                if turn.delta is not None:
                    try:
                        branch.state, summary = branch.state.apply(turn.delta)
                    except ValueError as error:
                        branch.status = "ready_to_synthesize"
                        branch.stop_reason = "progress_state_transition_invalid"
                        trace.add(
                            "autonomous_turn_failed",
                            agent_role=branch.role,
                            candidate_id=branch.candidate_id,
                            mode=branch.mode,
                            failure_code=branch.stop_reason,
                            detail=type(error).__name__,
                            next_action="synthesize_candidate",
                        )
                        continue
                trace.add(
                    "autonomous_agent_action",
                    agent_role=branch.role,
                    candidate_id=branch.candidate_id,
                    mode=branch.mode,
                    action=turn.action,
                    partial=turn.partial,
                    truncation_reason=turn.parsed.truncation_reason,
                    progress_summary=turn.parsed.payload.progress_summary,
                    semantic_sha256=decision.semantic_sha256,
                    information_gain=decision.information_gain,
                    state_version=branch.state.version,
                    outbound_intents=list(
                        turn.parsed.payload.outbound_intents
                    ),
                )
                if not decision.continue_allowed:
                    stall_stops += 1
                    branch.status = "ready_to_synthesize"
                    branch.stop_reason = decision.stop_reason
                    trace.add(
                        "autonomous_stall_detected",
                        agent_role=branch.role,
                        candidate_id=branch.candidate_id,
                        **decision.to_dict(),
                    )
                    continue
                if turn.action == "abstain":
                    branch.status = "abstained"
                    branch.stop_reason = turn.parsed.payload.stop_reason
                    trace.add(
                        "candidate_generation_started",
                        candidate_id=branch.candidate_id,
                        role=branch.role,
                        planned_method_family=branch.method_family,
                        turn_kind="agent_abstention",
                        autonomous=True,
                    )
                    trace.add(
                        "candidate_generation_failed",
                        **candidate_failure_trace_payload(
                            branch.candidate_id,
                            "agent_abstained",
                        ),
                        role=branch.role,
                        public_reason=branch.stop_reason,
                    )
                    continue
                if turn.action == "complete":
                    branch.status = "ready_to_synthesize"
                    branch.stop_reason = (
                        turn.parsed.payload.stop_reason
                        or "agent_requested_candidate_synthesis"
                    )
                    continue
                if turn.action == "request_tool_check":
                    self._apply_autonomous_tool_request(
                        session,
                        trace,
                        branch,
                        turn.delta,
                        summary,
                    )
                elif turn.action == "request_lemma":
                    branch.skill_context += self._answer_solver_lemma_request(
                        session,
                        trace,
                        branch,
                        turn.parsed.payload.outbound_intents,
                    )
                elif turn.action == "request_replan":
                    self._answer_solver_replan_request(
                        session,
                        trace,
                        branch,
                    )
                branch.mode = "continue"
            if not cycle_advanced and all(
                branch.status != "exploring" for branch in branches
            ):
                break

        candidates = []
        failures: list[BranchFailure] = []
        candidate_attempts = len(branches)
        candidate_synthesis_attempts = 0
        compact_recoveries = 0
        proof_degradations = 0
        for branch in branches:
            if branch.status == "abstained":
                failures.append(
                    BranchFailure(branch.candidate_id, "agent_abstained")
                )
                continue
            candidate_synthesis_attempts += 1
            trace.add(
                "candidate_generation_started",
                candidate_id=branch.candidate_id,
                role=branch.role,
                planned_method_family=branch.method_family,
                turn_kind=(
                    "solver_candidate_proof"
                    if session.problem_ir.response_mode == "proof_full"
                    else "solver_candidate_standard"
                ),
                autonomous=True,
            )
            try:
                compressed = self._compress_reasoning_state(branch.state, trace)
                request = SolverRequest(
                    branch.candidate_id,
                    session.problem_ir,
                    session.route_plan,
                    branch.skill_context
                    + self._autonomous_budget_context(
                        session.budget.snapshot()
                    ),
                    branch.method_family,
                    branch.forbidden_method_families,
                    branch.context_view,
                    compressed.prompt_json,
                )
                turn = self._solver_executor.execute_autonomous_candidate(
                    branch.solver,
                    request,
                    session.budget,
                    temperature=(
                        self._config.primary_temperature
                        if branch.role == "PrimarySolver"
                        else max(self._config.primary_temperature, 0.35)
                    ),
                    max_tokens=self._config.primary_max_tokens,
                )
                if turn.partial:
                    compact_recoveries += 1
                    trace.add(
                        "candidate_partial_recovery_started",
                        candidate_id=branch.candidate_id,
                        truncation_reason=turn.parsed.truncation_reason,
                        recovery_turn_kind="solver_compact_synthesis",
                        raw_response_reused=False,
                    )
                    turn = self._solver_executor.execute_autonomous_candidate(
                        branch.solver,
                        request,
                        session.budget,
                        temperature=0.0,
                        max_tokens=self._config.primary_max_tokens,
                        compact=True,
                    )
                if turn.action == "abstain" or turn.candidate is None:
                    failures.append(
                        BranchFailure(branch.candidate_id, "agent_abstained")
                    )
                    branch.status = "abstained"
                    trace.add(
                        "candidate_generation_failed",
                        **candidate_failure_trace_payload(
                            branch.candidate_id,
                            "agent_abstained",
                        ),
                        role=branch.role,
                    )
                    continue
                branch.candidate = turn.candidate
                branch.status = "candidate_published"
                candidates.append(turn.candidate)
                trace.add(
                    "candidate_generated",
                    **candidate_trace_payload(turn.candidate),
                    autonomous=True,
                )
            except ModelTransportError as error:
                if session.problem_ir.response_mode == "proof_full":
                    proof_degradations += 1
                    trace.add(
                        "proof_token_canary_degraded",
                        candidate_id=branch.candidate_id,
                        requested_tokens=12288,
                        fallback_tokens=8192,
                        failure_code=error.code,
                    )
                    try:
                        turn = self._solver_executor.execute_autonomous_candidate(
                            branch.solver,
                            request,
                            session.budget,
                            temperature=0.0,
                            max_tokens=8192,
                            compact=True,
                        )
                        if turn.candidate is not None and not turn.partial:
                            branch.candidate = turn.candidate
                            branch.status = "candidate_published"
                            candidates.append(turn.candidate)
                            trace.add(
                                "candidate_generated",
                                **candidate_trace_payload(turn.candidate),
                                autonomous=True,
                                proof_token_degraded=True,
                            )
                            continue
                    except Exception as retry_error:
                        error = retry_error
                reason = self._reasoning_failure_code(error)
                failures.append(BranchFailure(branch.candidate_id, reason))
                trace.add(
                    "candidate_generation_failed",
                    **candidate_failure_trace_payload(
                        branch.candidate_id,
                        reason,
                    ),
                    role=branch.role,
                )
            except Exception as error:
                reason = self._reasoning_failure_code(error)
                failures.append(BranchFailure(branch.candidate_id, reason))
                trace.add(
                    "candidate_generation_failed",
                    **candidate_failure_trace_payload(
                        branch.candidate_id,
                        reason,
                    ),
                    role=branch.role,
                )

        primary_state = branches[0].state
        return (
            FanoutResult(candidates, failures),
            primary_state,
            {
                "action_turns": action_turns,
                "progress_turns": progress_turns,
                "candidate_attempts": candidate_attempts,
                "candidate_synthesis_attempts": candidate_synthesis_attempts,
                "abstained_agents": sum(
                    branch.status == "abstained" for branch in branches
                ),
                "stall_stops": stall_stops,
                "compact_recoveries": compact_recoveries,
                "proof_token_degradations": proof_degradations,
                "agent_stop_reasons": {
                    branch.role: branch.stop_reason for branch in branches
                },
            },
        )

    def _run_solver_peer_review_phase(
        self,
        session,
        trace: TraceBuilder,
        candidates: list,
        *,
        review_candidate_ids: tuple[str, str] | None = None,
    ) -> list:
        incremental = review_candidate_ids is not None
        pool = (
            session.candidate_pool
            if incremental and session.candidate_pool is not None
            else CandidatePool()
        )
        session.candidate_pool = pool
        solver_candidates = [
            candidate
            for candidate in candidates
            if candidate.role in {"PrimarySolver", "AlternativeSolver"}
            and candidate.source.startswith("llm_")
        ]
        for candidate in solver_candidates:
            try:
                pool.entry(candidate.candidate_id)
            except KeyError:
                pass
            else:
                continue
            try:
                lineage = session.agent_runtime.candidate_publication(
                    candidate.candidate_id
                )
                pool.submit(candidate, **{
                    key: lineage[key]
                    for key in (
                        "author_agent_id",
                        "source_turn_id",
                        "candidate_artifact_id",
                    )
                })
            except (KeyError, ValueError) as error:
                trace.add(
                    "candidate_pool_registration_failed",
                    candidate_id=candidate.candidate_id,
                    failure_code=type(error).__name__,
                )
        independent = list(pool.independent_entries())
        trace.add(
            "candidate_pool_initialized",
            entries=pool.snapshot(),
            submitted_count=len(solver_candidates),
            independent_count=len(independent),
            structural_independence_gate=True,
            candidate_isolation_released=True,
            incremental=incremental,
        )
        if review_candidate_ids is None:
            by_role = {
                next(
                    candidate.role
                    for candidate in solver_candidates
                    if candidate.candidate_id == entry.candidate_id
                ): entry
                for entry in independent
            }
            review_entries = (
                by_role.get("PrimarySolver"),
                by_role.get("AlternativeSolver"),
            )
        else:
            independent_by_id = {
                entry.candidate_id: entry for entry in independent
            }
            review_entries = tuple(
                independent_by_id.get(candidate_id)
                for candidate_id in review_candidate_ids
            )
        if any(entry is None for entry in review_entries):
            trace.add(
                "solver_peer_review_phase_completed",
                status="independence_gate_failed",
                bidirectional_reviews=0,
                rebuttals=0,
                candidate_pool=pool.snapshot(),
            )
            active_ids = set(pool.active_candidate_ids())
            return [
                candidate
                for candidate in candidates
                if candidate.role not in {"PrimarySolver", "AlternativeSolver"}
                or candidate.candidate_id in active_ids
            ]

        candidate_by_id = {
            candidate.candidate_id: candidate for candidate in solver_candidates
        }
        first_entry, second_entry = review_entries
        pairs = (
            (first_entry, second_entry),
            (second_entry, first_entry),
        )
        review_outcomes = []
        for reviewer_entry, target_entry in pairs:
            reviewer = candidate_by_id[reviewer_entry.candidate_id]
            target = candidate_by_id[target_entry.candidate_id]
            pool.mark_peer_reviewing(target.candidate_id)
            trace.add(
                "peer_review_started",
                reviewer_role=reviewer.role,
                reviewer_agent_id=reviewer_entry.author_agent_id,
                author_agent_id=target_entry.author_agent_id,
                candidate_id=target.candidate_id,
                candidate_version=target.version,
                candidate_artifact_id=target_entry.candidate_artifact_id,
                independent_model_call=True,
            )
            try:
                outcome = self._peer_review_agent.review(
                    problem=session.problem_ir,
                    candidate=target,
                    candidate_artifact_id=target_entry.candidate_artifact_id,
                    author_agent_id=target_entry.author_agent_id,
                    reviewer_agent_id=reviewer_entry.author_agent_id,
                    reviewer_role=reviewer.role,
                    reviewer_candidate_id=reviewer.candidate_id,
                    obligations=session.problem_obligations,
                    budget=session.budget,
                    max_tokens=self._config.primary_max_tokens,
                )
            except Exception as error:
                trace.add(
                    "peer_review_completed",
                    status="failed",
                    reviewer_role=reviewer.role,
                    candidate_id=target.candidate_id,
                    independent_model_call=True,
                    failure_code=self._reasoning_failure_code(error),
                )
                continue
            session.peer_reviews.append(outcome.record)
            review_outcomes.append(outcome)
            pool.attach_review(
                target.candidate_id,
                outcome.record.review_id,
                challenged=outcome.record.challenged,
            )
            trace.add(
                "peer_review_completed",
                status="completed",
                review_id=outcome.record.review_id,
                reviewer_role=reviewer.role,
                reviewer_agent_id=reviewer_entry.author_agent_id,
                author_agent_id=target_entry.author_agent_id,
                candidate_id=target.candidate_id,
                candidate_version=target.version,
                finding_ids=[
                    item.finding_id for item in outcome.record.finding_items
                ],
                claim_ids=[item.claim_id for item in outcome.record.finding_items],
                challenged=outcome.record.challenged,
                independent_model_call=True,
                host_generated=False,
                artifact_id=outcome.artifact_id,
                message_id=outcome.message_id,
                thread_id=outcome.thread_id,
            )

        rebuttal_count = 0
        for review_outcome in review_outcomes:
            review = review_outcome.record
            target = candidate_by_id[review.candidate_id]
            target_entry = pool.entry(target.candidate_id)
            trace.add(
                "rebuttal_started",
                review_id=review.review_id,
                candidate_id=target.candidate_id,
                author_agent_id=target_entry.author_agent_id,
                reviewer_agent_id=review.reviewer_agent_id,
                finding_ids=[item.finding_id for item in review.finding_items],
                independent_model_call=True,
                thread_id=review_outcome.thread_id,
            )
            try:
                outcome = self._peer_review_agent.rebut(
                    candidate=target,
                    review=review,
                    author_agent_id=target_entry.author_agent_id,
                    reviewer_agent_id=review.reviewer_agent_id,
                    author_role=target.role,
                    author_candidate_id=target.candidate_id,
                    budget=session.budget,
                    max_tokens=self._config.primary_max_tokens,
                )
            except Exception as error:
                trace.add(
                    "rebuttal_completed",
                    status="failed",
                    review_id=review.review_id,
                    candidate_id=target.candidate_id,
                    independent_model_call=True,
                    failure_code=self._reasoning_failure_code(error),
                    thread_id=review_outcome.thread_id,
                )
                continue
            rebuttal_count += 1
            session.rebuttals.append(outcome.record)
            pool.attach_rebuttal(
                target.candidate_id,
                outcome.record.rebuttal_id,
                conceded_finding_ids=outcome.record.conceded_finding_ids,
            )
            trace.add(
                "rebuttal_completed",
                status="completed",
                rebuttal_id=outcome.record.rebuttal_id,
                review_id=review.review_id,
                candidate_id=target.candidate_id,
                finding_ids=[item.finding_id for item in outcome.record.responses],
                actions=[item.action for item in outcome.record.responses],
                conceded_finding_ids=list(outcome.record.conceded_finding_ids),
                independent_model_call=True,
                artifact_id=outcome.artifact_id,
                message_id=outcome.message_id,
                thread_id=outcome.thread_id,
                thread_status="closed",
            )

        active_ids = set(pool.active_candidate_ids())
        trace.add(
            "solver_peer_review_phase_completed",
            status=(
                "completed"
                if len(review_outcomes) == 2 and rebuttal_count == 2
                else "partial"
            ),
            bidirectional_reviews=len(review_outcomes),
            rebuttals=rebuttal_count,
            active_candidate_ids=sorted(active_ids),
            candidate_pool=pool.snapshot(),
            downstream_candidate_filter_applied=True,
        )
        return [
            candidate
            for candidate in candidates
            if candidate.role not in {"PrimarySolver", "AlternativeSolver"}
            or candidate.candidate_id in active_ids
        ]

    def _run_initial_llm_lemma_curator(
        self,
        session,
        trace: TraceBuilder,
    ) -> str:
        plan = session.agent_plan
        conditions = tuple(
            dict.fromkeys(
                (
                    *session.problem_ir.definitions,
                    *session.problem_ir.quantifiers,
                    *session.problem_ir.constraints,
                    *session.problem_ir.assumptions,
                )
            )
        )
        try:
            outcome = self._llm_lemma_curator.execute(
                LLMLemmaRequest(
                    problem=session.problem_ir.normalized_problem,
                    plan_id=plan.plan_id,
                    plan_summary="; ".join(
                        subgoal.objective for subgoal in plan.subgoals
                    ),
                    conditions=conditions,
                    target_obligation_ids=tuple(
                        subgoal.subgoal_id for subgoal in plan.subgoals
                    ),
                    request_text=(
                        "Identify problem-local lemmas and theorem conditions "
                        "that both independent Solvers should address."
                    ),
                    recipient_role="PrimarySolver",
                ),
                session.budget,
                max_tokens=self._config.primary_max_tokens,
                optional=False,
            )
        except Exception as error:
            trace.add(
                "llm_lemma_curator_completed",
                status="failed",
                independent_model_call=True,
                failure_code=self._reasoning_failure_code(error),
                fallback="deterministic_post_candidate_curation",
            )
            return ""
        session.lemmas.extend(outcome.lemmas)
        alternative_message_id = ""
        if self._config.enable_alternatives and outcome.turn_id:
            alternative_message_id = session.agent_runtime.relay_turn_artifact(
                outcome.turn_id,
                recipient_role="AlternativeSolver",
                message_type="lemma_published",
                public_summary=(
                    "LemmaCurator shared initial provisional lemmas with the "
                    "isolated AlternativeSolver"
                ),
            )
        trace.add(
            "llm_lemma_curator_completed",
            status="partial" if outcome.parsed.partial else "completed",
            independent_model_call=True,
            action=outcome.parsed.payload.action,
            lemma_ids=[lemma.lemma_id for lemma in outcome.lemmas],
            lemma_status="provisional",
            hard_fact_eligible=False,
            reply_recipient_role="PrimarySolver",
            alternative_message_id=alternative_message_id,
        )
        return self._proposed_lemma_context(outcome.lemmas)

    def _answer_solver_lemma_request(
        self,
        session,
        trace: TraceBuilder,
        branch: _AutonomousBranch,
        intents: tuple[dict[str, Any], ...],
    ) -> str:
        intent = intents[0] if intents else {}
        request_text = str(
            intent.get("request", intent.get("target", "Resolve the blocked public obligation."))
        )
        obligation_ids = tuple(
            str(item)
            for item in intent.get("target_obligation_ids", [])
            if str(item)
        )
        try:
            outcome = self._llm_lemma_curator.execute(
                LLMLemmaRequest(
                    problem=session.problem_ir.normalized_problem,
                    plan_id=session.agent_plan.plan_id,
                    plan_summary=branch.state.strategy,
                    conditions=tuple(session.problem_ir.assumptions),
                    target_obligation_ids=obligation_ids,
                    request_text=request_text,
                    recipient_role=branch.role,
                    source_round=max(1, branch.state.version + 1),
                ),
                session.budget,
                max_tokens=self._config.primary_max_tokens,
                optional=True,
            )
        except Exception as error:
            trace.add(
                "lemma_request_completed",
                requester_role=branch.role,
                status="failed",
                failure_code=self._reasoning_failure_code(error),
            )
            return ""
        session.lemmas.extend(outcome.lemmas)
        trace.add(
            "lemma_request_completed",
            requester_role=branch.role,
            status="completed",
            lemma_ids=[lemma.lemma_id for lemma in outcome.lemmas],
            solver_woken=True,
            hard_fact_eligible=False,
        )
        return self._proposed_lemma_context(outcome.lemmas)

    def _apply_autonomous_tool_request(
        self,
        session,
        trace: TraceBuilder,
        branch: _AutonomousBranch,
        delta,
        summary: dict[str, Any],
    ) -> None:
        if not self._config.enable_tools or delta is None:
            trace.add(
                "agent_tool_request_completed",
                requester_role=branch.role,
                status="unavailable",
                solver_woken=True,
            )
            return
        added = set(summary.get("added_claim_ids", []))
        batch = self._tool_feedback.run(
            tuple(claim for claim in delta.claims if claim.claim_id in added),
            domains=session.problem_ir.domains,
            assumptions=session.problem_ir.assumptions,
            selected_tools=session.route_plan.selected_tools,
            budget=session.budget,
        )
        if batch.work_items:
            branch.state, feedback = branch.state.apply_tool_results(
                batch.results
            )
            summary["evidence_ids"] = feedback["evidence_ids"]
        trace.add(
            "agent_tool_request_completed",
            requester_role=branch.role,
            status="completed" if batch.work_items else "no_supported_check",
            solver_woken=True,
            **batch.to_trace_dict(),
        )

    def _answer_solver_replan_request(
        self,
        session,
        trace: TraceBuilder,
        branch: _AutonomousBranch,
    ) -> None:
        previous = session.agent_plan
        try:
            outcome = self._context_route_stage.plan_authoritative(
                session.problem_ir,
                llm_chat=lambda **kwargs: self._provider.chat(
                    budget=session.budget,
                    stage="router",
                    turn_kind="replan",
                    agent_id="RouterPlanner",
                    **kwargs,
                ),
                consume_call=lambda: session.budget.consume(
                    stage="router",
                    optional=True,
                    action_category="replan",
                ),
                max_tokens=self._config.primary_max_tokens,
                previous_plan=previous,
                verified_fact_ids=tuple(
                    record.evidence_id
                    for record in session.evidence
                    if is_semantic_hard_pass(record)
                ),
                record_prompt_chars=session.budget.record_prompt_chars,
            )
            session.route_plan = outcome.route_plan
            session.agent_plan = outcome.authoritative_plan
            methods = session.route_plan.method_families
            if branch.candidate_id.startswith("new-branch-"):
                prior_methods = set(branch.forbidden_method_families)
                branch.method_family = next(
                    (
                        proposal.method_family
                        for proposal in session.agent_plan.task_proposals
                        if proposal.agent_role == branch.role
                        and proposal.method_family not in prior_methods
                    ),
                    branch.method_family,
                )
                branch.forbidden_method_families = tuple(sorted(prior_methods))
            else:
                method_index = 0 if branch.role == "PrimarySolver" else 1
                if method_index < len(methods):
                    branch.method_family = methods[method_index]
                    branch.forbidden_method_families = tuple(
                        method
                        for index, method in enumerate(methods[:2])
                        if index != method_index
                    )
            refs = session.agent_runtime.publish_router_decision(
                route_payload=session.route_plan.to_dict(),
                plan=session.agent_plan,
            )
        except Exception as error:
            trace.add(
                "agent_replan_completed",
                requester_role=branch.role,
                status="failed",
                failure_code=self._reasoning_failure_code(error),
            )
            return
        trace.add(
            "agent_replan_completed",
            requester_role=branch.role,
            status="completed",
            prior_plan_id=previous.plan_id,
            plan_id=session.agent_plan.plan_id,
            plan_version=session.agent_plan.version,
            solver_woken=True,
            **refs,
        )

    @staticmethod
    def _proposed_lemma_context(lemmas) -> str:
        if not lemmas:
            return ""
        lines = [
            "\n\nProposed problem-local lemmas (UNVERIFIED; these are targets, not facts):"
        ]
        lines.extend(
            f"- {lemma.lemma_id}: {lemma.statement}; conditions: "
            f"{', '.join(lemma.conditions) or 'none'}"
            for lemma in lemmas
        )
        return "\n".join(lines)

    @staticmethod
    def _autonomous_budget_context(snapshot) -> str:
        return (
            "\n\nPublic resource state: "
            f"session_calls_remaining={snapshot.remaining_calls}; "
            f"budget_pressure={snapshot.budget_phase}; "
            f"next_soft_checkpoint={snapshot.next_checkpoint}; "
            f"exploration_open={str(snapshot.exploration_open).lower()}. "
            "Use this only to choose a public Action; the Host remains the "
            "sole authority for admission and limits."
        )

    def _run_long_horizon_primary(
        self,
        session,
        trace: TraceBuilder,
        plan: LongHorizonPlan,
        *,
        skill_context: str,
        context_view,
    ):
        state = session.reasoning_state
        solver = PrimarySolver(self._contracts)
        active_skill_context = skill_context
        skill_failure_codes: tuple[str, ...] = ()
        method_families = list(session.route_plan.method_families)
        method_family = (
            method_families[0]
            if method_families
            else "direct-deduction"
        )
        forbidden = tuple(
            method_families[1 : session.route_plan.candidate_count]
        )
        degraded_reason = ""

        for progress_offset in range(plan.planned_rounds - 1):
            mode = "explore" if progress_offset == 0 else "continue"
            if progress_offset > 0:
                remaining_sequence = ["primary"] * (
                    plan.planned_rounds - progress_offset
                )
                if not stage_sequence_feasible(
                    remaining_sequence,
                    remaining_seconds=(
                        session.budget.snapshot().remaining_seconds
                    ),
                    maximum_queue_seconds=(
                        self._config.model_queue_budget_seconds
                    ),
                ):
                    degraded_reason = "continuation_time_reserve_unavailable"
                    break
            try:
                compressed = self._compress_reasoning_state(state, trace)
            except ContextBudgetExceeded:
                degraded_reason = "reasoning_state_budget_infeasible"
                if progress_offset == 0:
                    return None, state, degraded_reason
                break
            request = SolverRequest(
                "primary-1",
                session.problem_ir,
                session.route_plan,
                active_skill_context,
                method_family,
                forbidden,
                context_view,
                compressed.prompt_json,
            )
            try:
                delta = self._solver_executor.execute_progress(
                    solver,
                    request,
                    session.budget,
                    mode=mode,
                    temperature=self._config.primary_temperature,
                    max_tokens=self._config.primary_max_tokens,
                    optional=mode == "continue",
                )
                state, summary = state.apply(delta)
            except Exception as error:
                degraded_reason = self._reasoning_failure_code(error)
                trace.add(
                    "round_summary",
                    state_id=state.state_id,
                    state_version=state.version,
                    round_index=state.version,
                    mode=mode,
                    added_subgoal_ids=[],
                    updated_subgoal_ids=[],
                    closed_subgoal_ids=[],
                    added_claim_ids=[],
                    claim_dependency_refs={},
                    evidence_ids=list(state.evidence_refs),
                    opened_obligation_ids=[],
                    closed_obligation_ids=[],
                    information_gain=0,
                    next_step="fallback_to_synthesize",
                    stop_reason="progress_round_failed",
                    degraded_reason=degraded_reason,
                    state_tokens=compressed.state_tokens,
                    state_counting_mode=compressed.counting_mode,
                    state_compressed=compressed.compressed,
                    omitted_rounds=compressed.omitted_rounds,
                )
                if progress_offset == 0:
                    return None, state, degraded_reason
                break
            added_claim_ids = set(summary["added_claim_ids"])
            feedback_batch = None
            if self._config.enable_tools and added_claim_ids:
                feedback_batch = self._tool_feedback.run(
                    tuple(
                        claim
                        for claim in delta.claims
                        if claim.claim_id in added_claim_ids
                    ),
                    domains=session.problem_ir.domains,
                    assumptions=session.problem_ir.assumptions,
                    selected_tools=session.route_plan.selected_tools,
                    budget=session.budget,
                )
                if feedback_batch.work_items:
                    state, feedback_summary = state.apply_tool_results(
                        feedback_batch.results
                    )
                    summary["evidence_ids"] = feedback_summary[
                        "evidence_ids"
                    ]
                    skill_failure_codes = feedback_batch.failure_codes
                    trace.add(
                        "tool_feedback_completed",
                        state_id=state.state_id,
                        state_version=state.version,
                        round_index=delta.round_index,
                        next_protocol=(
                            "continue"
                            if progress_offset
                            < plan.planned_rounds - 2
                            else "synthesize"
                        ),
                        **feedback_batch.to_trace_dict(),
                    )
                    if skill_failure_codes:
                        dynamic_primary = (
                            self._dynamic_skills.compose_for_role(
                                session.problem_ir,
                                role="PrimarySolver",
                                route_skill_names=(
                                    session.route_plan.selected_skills
                                ),
                                max_chars=self._config.skill_char_budget,
                                state=state,
                                failure_codes=skill_failure_codes,
                                selection_context=(
                                    f"tool_feedback_round_{delta.round_index}"
                                ),
                            )
                        )
                        active_skill_context = dynamic_primary.text
                        self._trace_dynamic_skill_selection(
                            trace,
                            {"PrimarySolver": dynamic_primary},
                            selection_context=(
                                f"tool_feedback_round_{delta.round_index}"
                            ),
                        )
            try:
                committed_state = self._compress_reasoning_state(
                    state,
                    trace,
                )
            except ContextBudgetExceeded:
                committed_state = compressed
                degraded_reason = "reasoning_state_budget_infeasible"
            trace.add(
                "round_summary",
                **{
                    **summary,
                    "stop_reason": (
                        summary["stop_reason"]
                        if summary["information_gain"] > 0
                        else "no_information_gain"
                    ),
                },
                state_tokens=committed_state.state_tokens,
                state_counting_mode=committed_state.counting_mode,
                state_compressed=committed_state.compressed,
                omitted_rounds=committed_state.omitted_rounds,
            )
            session.reasoning_state = state
            if summary["information_gain"] <= 0 or degraded_reason:
                break

        try:
            compressed = self._compress_reasoning_state(state, trace)
        except ContextBudgetExceeded:
            return None, state, (
                degraded_reason or "synthesis_state_budget_infeasible"
            )
        request = SolverRequest(
            "primary-1",
            session.problem_ir,
            session.route_plan,
            active_skill_context,
            method_family,
            forbidden,
            context_view,
            compressed.prompt_json,
        )
        try:
            candidate = self._solver_executor.execute(
                solver,
                request,
                session.budget,
                temperature=self._config.primary_temperature,
                max_tokens=self._config.primary_max_tokens,
                optional=False,
            )
        except Exception as error:
            return None, state, (
                degraded_reason or self._reasoning_failure_code(error)
            )
        return candidate, state, degraded_reason

    def _compress_reasoning_state(
        self,
        state: ReasoningState,
        trace: TraceBuilder,
    ):
        compressed = self._reasoning_state_compressor.compress(
            state,
            max_tokens=REASONING_STATE_MAX_TOKENS,
        )
        trace.add(
            "compression_validated",
            role="PrimarySolver",
            state_id=state.state_id,
            state_version=state.version,
            state_tokens=compressed.state_tokens,
            counting_mode=compressed.counting_mode,
            compressed=compressed.compressed,
            omitted_rounds=compressed.omitted_rounds,
            preserved_invariants=list(compressed.semantic_invariants),
        )
        return compressed

    def _trace_dynamic_skill_selection(
        self,
        trace: TraceBuilder,
        compositions,
        *,
        selection_context: str,
    ) -> None:
        trace.add(
            "skills_selected",
            selection_context=selection_context,
            skills=[
                {
                    "name": decision.name,
                    "version": decision.version,
                    "role": role,
                    "rank": decision.rank,
                    "score": decision.score,
                    "reason": ";".join(decision.reasons),
                    "included_sections": list(
                        decision.included_sections
                    ),
                    "omitted_sections": list(
                        decision.omitted_sections
                    ),
                }
                for role, composition in compositions.items()
                for decision in composition.included
            ],
            omitted_by_role={
                role: [
                    {
                        "name": decision.name,
                        "rank": decision.rank,
                        "score": decision.score,
                        "reasons": list(decision.reasons),
                    }
                    for decision in composition.omitted
                ]
                for role, composition in compositions.items()
                if composition.omitted
            },
            skill_fingerprint=self._skills.fingerprint,
        )

    @staticmethod
    def _reasoning_failure_code(error: Exception) -> str:
        code = str(getattr(error, "code", "")).strip()
        if code and all(
            character.isalnum() or character in {"_", "-"}
            for character in code
        ):
            return code[:128]
        if isinstance(error, ContextBudgetExceeded):
            return "reasoning_context_budget_exceeded"
        if isinstance(error, BudgetExceeded):
            return "reasoning_budget_or_deadline_exceeded"
        return "reasoning_state_transition_invalid"

    def _provider_health_state(self) -> str:
        state = str(self._model_gate.health_snapshot().get("state", "healthy"))
        return state if state in {"healthy", "degraded", "circuit_open"} else "healthy"

    def _provider_allows_optional_model_work(self) -> bool:
        """Keep a degraded shared provider focused on answer formation."""
        return self._provider_health_state() == "healthy"

    def _run_shadow_probe(self, problem_ir) -> ShadowOutcome:
        executor = self._shadow_executor
        if executor is None:
            return ShadowOutcome("unsupported", "", "")
        timeout = min(5.0, self._config.max_tool_seconds)
        started = perf_counter()
        result = executor.execute(
            "deterministic_shadow_probe",
            {
                "problem_ir": problem_ir.to_dict(),
                "time_budget_seconds": timeout,
            },
            timeout=timeout,
        )
        payload = result.payload.get("outcome")
        if isinstance(payload, dict):
            try:
                return ShadowOutcome.from_dict(payload)
            except (TypeError, ValueError):
                pass
        return ShadowOutcome(
            "failed",
            "",
            problem_ir.normalized_problem,
            limitations=(
                "shadow_time_budget_exhausted"
                if "timed out" in result.summary
                else "isolated_shadow_probe_failed",
            ),
            elapsed_seconds=round(perf_counter() - started, 6),
        )

    @staticmethod
    def _shadow_consistency(
        primary,
        shadow: ShadowOutcome | None,
        answer_type: str,
    ) -> str:
        if primary is None or shadow is None or not shadow.exact:
            return "not_available"
        return (
            "consistent"
            if canonical_answer(primary.final_answer, answer_type)
            == canonical_answer(shadow.final_answer, answer_type)
            else "conflict"
        )

    def _validated_final_response(
        self,
        text: str,
        *,
        exact_answer: str,
        answer_type: str,
        response_mode: str,
    ):
        text = canonical_final_response(
            text,
            exact_answer=exact_answer,
            answer_type=answer_type,
            response_mode=response_mode,
        )
        text = bound_final_response(
            text,
            exact_answer=exact_answer,
            max_chars=self._config.final_response_max_chars,
            answer_type=answer_type,
            response_mode=response_mode,
        )
        try:
            return text, self._context_budget.ensure_text_within_window(text)
        except ContextBudgetExceeded:
            blocks = text.split("\n\n")
            deduplicated = "\n\n".join(dict.fromkeys(blocks))
            return (
                deduplicated,
                self._context_budget.ensure_text_within_window(deduplicated),
            )

    @staticmethod
    def _transition(
        session,
        trace: TraceBuilder,
        expected: RuntimePhase,
        target: RuntimePhase,
        reason: str,
    ) -> None:
        transition = session.transition(expected, target, reason=reason)
        trace.add("phase_transition", **transition)

    def _build_role_context(
        self,
        session,
        blackboard: MemoryBlackboard,
        trace: TraceBuilder,
        *,
        role: str,
        candidates=None,
        evidence=None,
        focus_claim_ids: list[str] | None = None,
        final_answer: str = "",
        memory_categories: set[str] | frozenset[str] | None = None,
    ):
        session.budget.ensure_stage("context_compression")
        role_directory = _ROLE_CONTRACT_DIRECTORIES[role]
        contract_budget = self._contracts.load(role_directory).max_context_chars
        view_budget = min(
            self._config.raw_context_max_chars,
            max(256, contract_budget // 2),
        )
        use_all_candidates = candidates is None
        selected_candidates = (
            list(session.candidates) if use_all_candidates else list(candidates)
        )
        candidate_ids = {candidate.candidate_id for candidate in selected_candidates}
        selected_evidence = (
            [
                record
                for record in session.evidence
                if use_all_candidates or record.candidate_id in candidate_ids
                if record.transaction_status == "active"
            ]
            if evidence is None
            else list(evidence)
        )
        selected_obligations = {
            candidate_id: items
            for candidate_id, items in session.proof_obligations.items()
            if use_all_candidates or candidate_id in candidate_ids
        }
        if session.problem_obligations:
            selected_obligations = {
                "__problem__": list(session.problem_obligations),
                **selected_obligations,
            }
        try:
            view = self._context_route_stage.build_context(
                problem=session.problem_ir,
                candidates=selected_candidates,
                evidence=selected_evidence,
                obligations=selected_obligations,
                blackboard=blackboard,
                role=role,
                max_chars=view_budget,
                focus_claim_ids=focus_claim_ids,
                final_answer=final_answer,
                raw_store=session.raw_context_store,
                memory_categories=memory_categories,
            )
        except ContextBudgetExceeded:
            trace.add(
                "context_budget_infeasible",
                role=role,
                max_chars=view_budget,
                reason="budget_infeasible",
            )
            raise
        trace.add(
            "context_view_built",
            role=role,
            snapshot_id=view.snapshot_id,
            chars=view.char_count,
            max_chars=view.max_chars,
        )
        return view

    def _repair_candidate(
        self,
        session,
        blackboard: MemoryBlackboard,
        trace: TraceBuilder,
        candidate,
        affected_claim_ids: list[str],
        local_evidence,
        skill_context: str,
    ):
        context_view = self._build_role_context(
            session,
            blackboard,
            trace,
            role="RepairAgent",
            candidates=[candidate],
            evidence=local_evidence,
            focus_claim_ids=affected_claim_ids,
        )
        critique = next(
            (
                item
                for item in reversed(session.critiques)
                if any(
                    finding.candidate_id == candidate.candidate_id
                    and finding.claim_id in affected_claim_ids
                    for finding in item.findings
                )
            ),
            None,
        )
        return self._repair_agent.repair(
            session.problem_ir,
            candidate,
            affected_claim_ids,
            local_evidence,
            session.budget,
            max_tokens=self._config.primary_max_tokens,
            context_view=context_view,
            skill_context=skill_context,
            critique=critique.to_dict() if critique is not None else None,
            critique_artifact_id=(
                critique.artifact_id if critique is not None else ""
            ),
        )

    def _run_answer_type_check(self, session, candidate, ledger: EvidenceLedger):
        effective_answer_type = (
            session.problem_ir.answer_type
            if session.problem_ir.answer_type_confidence >= 0.75
            else candidate.answer_type
        )
        arguments = {
            "answer": candidate.final_answer,
            "answer_type": effective_answer_type,
        }
        timeout = session.budget.begin_tool_call(
            isolated=self._tool_executor.is_isolated("answer_type_check"),
            default_timeout=self._tool_executor.default_timeout,
        )
        started = perf_counter()
        try:
            result = self._tool_executor.execute(
                "answer_type_check",
                arguments,
                timeout=timeout,
            )
        finally:
            duration_seconds = perf_counter() - started
            session.budget.finish_tool_call(duration_seconds)
        duration_ms = duration_seconds * 1000
        records = []
        if self._config.enable_evidence:
            records.append(
                ledger.record_tool_result(
                    candidate_id=candidate.candidate_id,
                    claim_id=None,
                    result=result,
                    arguments=arguments,
                    assumptions=list(
                        dict.fromkeys(
                            [*session.problem_ir.assumptions, *candidate.assumptions]
                        )
                    ),
                    domains=session.problem_ir.domains,
                    duration_ms=duration_ms,
                    timeout_seconds=timeout,
                    claim_kind="answer_shape",
                    input_complete=True,
                    context_complete=True,
                    request_status="ready",
                    schema_valid=not self._tool_executor.validate_arguments(
                        "answer_type_check",
                        arguments,
                    ),
                )
            )
        return result, records

    def _reverify_repair_candidate(
        self,
        session,
        candidate,
        ledger: EvidenceLedger,
        affected_claim_ids: list[str],
    ):
        ledger.register_candidate(candidate)
        admission = self._candidate_stage.evaluate(
            candidate,
            session.problem_ir,
        )
        if not admission.accepted:
            raise CandidateAdmissionError(
                ",".join(admission.rejection_codes)
            )
        answer_shape, records = self._run_answer_type_check(
            session,
            candidate,
            ledger,
        )
        admission = self._candidate_stage.evaluate(
            candidate,
            session.problem_ir,
            answer_shape_status=answer_shape.status,
        )
        if not admission.accepted:
            return records
        records.extend(
            self._evidence_stage.verify(
                candidate,
                ledger,
                only_claim_ids=affected_claim_ids,
                domains=session.problem_ir.domains,
                assumptions=session.problem_ir.assumptions,
                budget=session.budget,
                selected_tools=session.route_plan.selected_tools,
            )
        )
        return records

    def _run_new_branch_cycle(
        self,
        session,
        blackboard: MemoryBlackboard,
        trace: TraceBuilder,
        candidates: list,
        ledger: EvidenceLedger,
        role_skill_contexts: dict[str, str],
    ):
        budget = session.budget.snapshot()
        if budget.remaining_calls < 7 or session.budget.deadline.must_finalize():
            trace.add(
                "new_branch_completed",
                status="not_started",
                reason="insufficient_closure_capacity",
                remaining_calls=budget.remaining_calls,
            )
            return None
        critique = session.critiques[-1]
        base = next(
            (item for item in candidates if item.role == "PrimarySolver"),
            candidates[0],
        )
        role = (
            "AlternativeSolver"
            if base.role == "PrimarySolver"
            else "PrimarySolver"
        )
        ordinal = 1 + sum(
            item.candidate_id.startswith("new-branch-")
            for item in session.candidates
        )
        candidate_id = f"new-branch-{ordinal}"
        prior_method_families = {
            item.method
            for item in session.candidates
            if item.role in {"PrimarySolver", "AlternativeSolver"}
        }
        if session.candidate_pool is not None:
            prior_method_families.update(
                str(item.get("method_signature", {}).get("method_family", ""))
                .strip()
                .replace(" ", "-")
                for item in session.candidate_pool.snapshot()
            )
            prior_method_families.discard("")
        methods = [
            method
            for method in session.route_plan.method_families
            if method not in prior_method_families
        ]
        method = methods[0] if methods else "independent-new-branch"
        context_view = self._build_role_context(
            session,
            blackboard,
            trace,
            role=role,
            candidates=candidates,
            evidence=session.evidence,
        )
        branch = _AutonomousBranch(
            role=role,
            candidate_id=candidate_id,
            solver=(
                AlternativeSolver(self._contracts)
                if role == "AlternativeSolver"
                else PrimarySolver(self._contracts)
            ),
            method_family=method,
            forbidden_method_families=tuple(
                sorted(prior_method_families)
            ),
            context_view=context_view,
            skill_context=(
                role_skill_contexts.get(role, "")
                + "\n\nVerifier Critique requiring a genuinely new method branch:\n"
                + json.dumps(
                    critique.to_dict(),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            ),
            state=ReasoningState.initialize(
                session.problem_ir,
                strategy=method,
            ),
        )
        prior_plan_id = session.agent_plan.plan_id
        self._answer_solver_replan_request(session, trace, branch)
        if session.agent_plan.plan_id == prior_plan_id:
            trace.add(
                "new_branch_completed",
                status="failed",
                reason="router_replan_failed",
                critique_id=critique.critique_id,
            )
            return None
        trace.add(
            "new_branch_started",
            candidate_id=candidate_id,
            role=role,
            critique_id=critique.critique_id,
            critique_artifact_id=critique.artifact_id,
            plan_id=session.agent_plan.plan_id,
            planned_method_family=branch.method_family,
            independent_model_call=True,
        )
        trace.add(
            "candidate_generation_started",
            candidate_id=candidate_id,
            role=role,
            planned_method_family=branch.method_family,
            turn_kind=(
                "solver_candidate_proof"
                if session.problem_ir.response_mode == "proof_full"
                else "solver_candidate_standard"
            ),
            autonomous=True,
            new_branch=True,
        )
        try:
            compressed = self._compress_reasoning_state(branch.state, trace)
            request = SolverRequest(
                candidate_id,
                session.problem_ir,
                session.route_plan,
                branch.skill_context,
                branch.method_family,
                branch.forbidden_method_families,
                context_view,
                compressed.prompt_json,
            )
            turn = self._solver_executor.execute_autonomous_candidate(
                branch.solver,
                request,
                session.budget,
                temperature=max(self._config.primary_temperature, 0.35),
                max_tokens=self._config.primary_max_tokens,
                input_artifact_ids=(
                    (critique.artifact_id,)
                    if critique.artifact_id
                    else ()
                ),
            )
            candidate = turn.candidate
            if turn.partial or candidate is None or turn.action == "abstain":
                raise ValueError("new branch did not publish a complete Candidate")
            admission = self._candidate_stage.evaluate(candidate, session.problem_ir)
            if not admission.accepted:
                raise CandidateAdmissionError(",".join(admission.rejection_codes))
        except Exception as error:
            trace.add(
                "new_branch_completed",
                status="failed",
                candidate_id=candidate_id,
                critique_id=critique.critique_id,
                failure_code=self._reasoning_failure_code(error),
            )
            return None
        session.candidates.append(candidate)
        trace.add(
            "candidate_generated",
            **candidate_trace_payload(candidate),
            autonomous=True,
            new_branch=True,
            parent_critique_id=critique.critique_id,
        )
        ledger.register_candidate(candidate)
        reviewed = self._run_solver_peer_review_phase(
            session,
            trace,
            [base, candidate],
            review_candidate_ids=(base.candidate_id, candidate.candidate_id),
        )
        if candidate.candidate_id not in {item.candidate_id for item in reviewed}:
            trace.add(
                "new_branch_completed",
                status="rejected",
                candidate_id=candidate_id,
                critique_id=critique.critique_id,
                reason="new_branch_peer_review_rejected",
            )
            return None
        answer_shape, _ = self._run_answer_type_check(session, candidate, ledger)
        admission = self._candidate_stage.evaluate(
            candidate,
            session.problem_ir,
            answer_shape_status=answer_shape.status,
        )
        if not admission.accepted:
            trace.add(
                "new_branch_completed",
                status="rejected",
                candidate_id=candidate_id,
                critique_id=critique.critique_id,
                reason="new_branch_answer_shape_rejected",
            )
            return None
        if self._config.enable_tools and self._config.enable_evidence:
            self._evidence_stage.verify(
                candidate,
                ledger,
                domains=session.problem_ir.domains,
                assumptions=session.problem_ir.assumptions,
                budget=session.budget,
                selected_tools=session.route_plan.selected_tools,
            )
        session.proof_obligations[candidate.candidate_id] = self._proof_stage.generate(
            session.problem_ir,
            candidate,
            problem_obligations=session.problem_obligations,
        )
        trace.add(
            "new_branch_completed",
            status="completed",
            candidate_id=candidate.candidate_id,
            role=candidate.role,
            critique_id=critique.critique_id,
            plan_id=session.agent_plan.plan_id,
            candidate_artifact_id=session.agent_runtime.candidate_publication(
                candidate.candidate_id
            )["candidate_artifact_id"],
            peer_review_reentered=True,
            independently_authored=True,
        )
        return candidate

    def _run_final_audit_phase(
        self,
        session,
        blackboard: MemoryBlackboard,
        trace: TraceBuilder,
        candidates: list,
        ledger: EvidenceLedger,
        skill_context: str,
    ) -> list:
        remaining = list(candidates)
        seen_audits: set[tuple] = set()
        while remaining and not session.budget.deadline.must_finalize():
            candidate = (
                remaining[0]
                if len(remaining) == 1
                else self._arbitration.select(
                    remaining,
                    session.evidence,
                    session.proof_obligations,
                ).selected
            )
            input_artifacts = list(
                self._verification_input_artifact_ids(
                    session,
                    {candidate.candidate_id},
                )
            )
            input_artifacts.extend(
                str(item.get("repair_artifact_id", ""))
                for item in session.repair_lineage
                if item.get("proposed_candidate_id") == candidate.candidate_id
            )
            input_artifacts = list(
                dict.fromkeys(item for item in input_artifacts if item)
            )
            trace.add(
                "final_audit_started",
                candidate_id=candidate.candidate_id,
                candidate_version=candidate.version,
                verifier_instance_ordinal=len(session.audits) + 1,
                input_artifact_ids=input_artifacts,
                independent_model_call=True,
            )
            try:
                outcome = self._verification_closure_agent.final_audit(
                    problem=session.problem_ir,
                    candidate=candidate,
                    obligations=session.proof_obligations.get(
                        candidate.candidate_id,
                        [],
                    ),
                    evidence=session.evidence,
                    critiques=session.critiques,
                    peer_reviews=session.peer_reviews,
                    rebuttals=session.rebuttals,
                    repair_lineage=session.repair_lineage,
                    input_artifact_ids=tuple(input_artifacts),
                    budget=session.budget,
                    max_tokens=self._config.primary_max_tokens,
                    ordinal=len(session.audits) + 1,
                )
            except Exception as error:
                trace.add(
                    "final_audit_completed",
                    status="unavailable",
                    candidate_id=candidate.candidate_id,
                    independent_model_call=True,
                    failure_code=self._reasoning_failure_code(error),
                    degraded=True,
                )
                break
            audit = outcome.record
            session.audits.append(audit)
            signature = (
                audit.candidate_id,
                audit.candidate_version,
                audit.status,
                audit.open_finding_ids,
                audit.open_obligation_ids,
                audit.requested_action,
            )
            trace.add(
                "final_audit_completed",
                **audit.to_dict(),
                independent_model_call=True,
                verifier_instance_distinct_from_cross_exam=True,
                candidate_scope_count=1,
            )
            if audit.complete:
                return remaining
            if audit.status == "failed" or audit.requested_action == "reject":
                remaining = [
                    item
                    for item in remaining
                    if item.candidate_id != candidate.candidate_id
                ]
                if session.candidate_pool is not None:
                    try:
                        session.candidate_pool.reject(
                            candidate.candidate_id,
                        )
                    except (KeyError, ValueError):
                        pass
                continue
            budget = session.budget.snapshot()
            can_reenter = (
                signature not in seen_audits
                and budget.remaining_calls >= 2
                and not session.budget.deadline.must_finalize()
                and audit.requested_action
                in {
                    "continue_review",
                    "local_repair",
                    "new_branch",
                    "replan",
                }
            )
            trace.add(
                "audit_reentry_decision",
                candidate_id=candidate.candidate_id,
                audit_id=audit.audit_id,
                requested_action=audit.requested_action,
                reentered=can_reenter,
                reason=(
                    "new_action_and_capacity"
                    if can_reenter
                    else "no_new_action_or_capacity"
                ),
            )
            if not can_reenter:
                break
            seen_audits.add(signature)
            before = len(session.critiques)
            self._run_skeptic_review(
                session,
                blackboard,
                trace,
                [candidate],
                ledger,
                skill_context,
                round_name=f"audit_reentry_{len(session.audits)}",
            )
            if len(session.critiques) == before:
                break
        return remaining

    def _run_skeptic_review(
        self,
        session,
        blackboard: MemoryBlackboard,
        trace: TraceBuilder,
        candidates,
        ledger: EvidenceLedger,
        skill_context: str,
        *,
        round_name: str,
    ):
        try:
            if self._config.enable_verification_closure:
                outcome = self._verification_closure_agent.cross_exam(
                    problem=session.problem_ir,
                    candidates=list(candidates),
                    candidate_pool=(
                        session.candidate_pool.snapshot()
                        if session.candidate_pool is not None
                        else []
                    ),
                    obligations=session.proof_obligations,
                    evidence=session.evidence,
                    peer_reviews=session.peer_reviews,
                    rebuttals=session.rebuttals,
                    input_artifact_ids=self._verification_input_artifact_ids(
                        session,
                        {item.candidate_id for item in candidates},
                    ),
                    budget=session.budget,
                    max_tokens=self._config.primary_max_tokens,
                    ordinal=len(session.critiques) + 1,
                )
                verifier_result = outcome.record
                session.critiques.append(outcome.record)
            else:
                verifier_context = self._build_role_context(
                    session,
                    blackboard,
                    trace,
                    role="VerifierSkeptic",
                    candidates=candidates,
                    evidence=session.evidence,
                )
                verifier_result = self._verifier_agent.review(
                    session.problem_ir,
                    candidates,
                    session.proof_obligations,
                    session.budget,
                    max_tokens=self._config.primary_max_tokens,
                    context_view=verifier_context,
                    evidence=session.evidence,
                    skill_context=skill_context,
                    peer_reviews=session.peer_reviews,
                    rebuttals=session.rebuttals,
                )
        except (
            BudgetExceeded,
            ModelTransportError,
            ContextBudgetExceeded,
        ):
            verifier_result = None
        verifier_reason = (
            getattr(verifier_result, "reason", "accepted")
            if verifier_result is not None
            else "verifier_unavailable"
        )
        if (
            verifier_result is None
            or (
                not getattr(verifier_result, "used_llm", True)
                and verifier_reason
                in {"verifier_unavailable", "finalize_cutoff"}
            )
        ):
            verifier_status = "unavailable"
        elif any(
            item.status.strip().lower() == "fail"
            for item in verifier_result.findings
        ):
            verifier_status = "fail"
        elif (
            not verifier_result.findings
            or any(
                item.status.strip().lower() == "unknown"
                for item in verifier_result.findings
            )
        ):
            verifier_status = "unknown"
        else:
            verifier_status = "pass"
        reviewed: set[str] = set()
        records = []
        for finding in (
            verifier_result.findings
            if verifier_result is not None
            else []
        ):
            records.append(
                ledger.record_verifier_finding(
                    candidate_id=finding.candidate_id,
                    claim_id=finding.claim_id,
                    obligation_ids=finding.obligation_ids,
                    status=finding.status,
                    description=getattr(
                        finding,
                        "description",
                        getattr(finding, "public_rationale", "Verifier finding"),
                    ),
                    missing_condition=finding.missing_condition,
                    counterexample_summary=finding.counterexample_summary,
                    review_level=getattr(
                        finding,
                        "review_level",
                        "obligation",
                    ),
                    review_target_ids=getattr(finding, "review_target_ids", ()),
                )
            )
            reviewed.add(finding.candidate_id)
        conflict_matrix = CandidateConflictMatrix.build(
            [
                CandidateReviewSummary.from_candidate(candidate)
                for candidate in candidates
            ],
            session.peer_reviews,
        )
        expected_review_target_ids = {
            target.target_id
            for target in conflict_matrix.review_targets()
        }
        completed_review_target_ids = {
            target_id
            for record in records
            for target_id in record.payload.get(
                "review_target_ids",
                [],
            )
        }
        trace.add(
            "verifier_completed",
            used_llm=(
                getattr(verifier_result, "used_llm", True)
                if verifier_result is not None
                else False
            ),
            finding_count=(
                len(verifier_result.findings)
                if verifier_result is not None
                else 0
            ),
            reviewed_candidates=sorted(reviewed),
            reason=verifier_reason,
            status=verifier_status,
            round=round_name,
            review_targets=sorted(expected_review_target_ids),
            reviewed_targets=sorted(completed_review_target_ids),
            unreviewed_targets=sorted(
                expected_review_target_ids
                - completed_review_target_ids
            ),
            critique_id=getattr(verifier_result, "critique_id", ""),
            critique_artifact_id=getattr(verifier_result, "artifact_id", ""),
            recommended_action=getattr(
                verifier_result,
                "recommended_action",
                "",
            ),
            peer_review_assessment_count=len(
                getattr(verifier_result, "peer_review_assessments", ())
            ),
            independent_model_call=bool(
                self._config.enable_verification_closure
                and verifier_result is not None
            ),
        )
        return verifier_result, verifier_reason, reviewed, records

    @staticmethod
    def _verification_input_artifact_ids(
        session,
        candidate_ids: set[str] | None = None,
    ) -> tuple[str, ...]:
        allowed = candidate_ids or set()
        values: list[str] = []
        if session.candidate_pool is not None:
            values.extend(
                str(item.get("candidate_artifact_id", ""))
                for item in session.candidate_pool.snapshot()
                if not allowed or str(item.get("candidate_id", "")) in allowed
            )
        known_candidate_artifacts = set(values)
        for candidate_id in sorted(allowed):
            try:
                publication = session.agent_runtime.candidate_publication(
                    candidate_id
                )
            except KeyError:
                continue
            artifact_id = publication["candidate_artifact_id"]
            if artifact_id not in known_candidate_artifacts:
                values.append(artifact_id)
                known_candidate_artifacts.add(artifact_id)
        values.extend(
            item.artifact_id
            for item in session.peer_reviews
            if (not allowed or item.candidate_id in allowed)
        )
        values.extend(
            item.artifact_id
            for item in session.rebuttals
            if (not allowed or item.candidate_id in allowed)
        )
        values.extend(
            item.artifact_id
            for item in session.critiques
            if item.artifact_id
            and (
                not allowed
                or any(
                    finding.candidate_id in allowed
                    for finding in item.findings
                )
            )
        )
        return tuple(dict.fromkeys(item for item in values if item))

    def _expand_with_verified_lemmas(
        self,
        session,
        blackboard: MemoryBlackboard,
        trace: TraceBuilder,
        verified_lemmas,
        round_id: int,
        skill_context: str,
    ):
        lemma_lines = [
            f"- {lemma.statement} (conditions: {', '.join(lemma.conditions) or 'none'})"
            for lemma in verified_lemmas
        ]
        expanded_skill_context = skill_context
        for line in lemma_lines:
            prefix = (
                "\n\nVerified problem-local lemmas:\n"
                if "Verified problem-local lemmas:" not in expanded_skill_context
                else "\n"
            )
            if (
                len(expanded_skill_context) + len(prefix) + len(line)
                > self._config.skill_char_budget
            ):
                continue
            expanded_skill_context = (
                f"{expanded_skill_context}{prefix}{line}"
            )
        request = SolverRequest(
            candidate_id=f"lemma-round-{round_id}",
            problem=session.problem_ir,
            route=session.route_plan,
            skill_context=expanded_skill_context,
            method_family="lemma-guided",
            context_view=self._build_role_context(
                session,
                blackboard,
                trace,
                role="PrimarySolver",
                candidates=[],
                evidence=[],
                memory_categories={"raw"},
            ),
        )
        trace.add(
            "candidate_generation_started",
            candidate_id=request.candidate_id,
            role="PrimarySolver",
            planned_method_family=request.method_family,
            source="verified_lemma_expansion",
        )
        try:
            candidate = self._solver_executor.execute(
                PrimarySolver(self._contracts),
                request,
                session.budget,
                temperature=self._config.primary_temperature,
                max_tokens=self._config.primary_max_tokens,
                optional=True,
            )
        except Exception:
            trace.add(
                "candidate_generation_failed",
                **candidate_failure_trace_payload(
                    request.candidate_id,
                    "lemma_expansion_failed",
                ),
            )
            raise
        trace.add(
            "candidate_generated",
            **candidate_trace_payload(candidate),
        )
        return candidate

    @staticmethod
    def _trace_candidate_evidence(
        trace: TraceBuilder,
        candidate,
        records,
        *,
        status: str,
        reason: str,
    ) -> None:
        active_records = [
            record
            for record in records
            if record.transaction_status == "active"
        ]
        claim_results = [
            {
                "claim_id": record.claim_id,
                "evidence_id": record.evidence_id,
                "check": record.evidence_type,
                "capability": record.capability,
                "status": record.status,
                "strength": record.strength,
                "summary": record.description,
            }
            for record in active_records
            if record.claim_id is not None
        ]
        answer_records = [
            record for record in active_records if record.claim_id is None
        ]
        answer_shape = (
            {
                "status": answer_records[-1].status,
                "strength": answer_records[-1].strength,
                "evidence_id": answer_records[-1].evidence_id,
                "summary": answer_records[-1].description,
            }
            if answer_records
            else {"status": "skipped", "strength": "none"}
        )
        claims_with_pass_evidence = {
            record.claim_id
            for record in active_records
            if record.claim_id is not None and record.status == "pass"
        }
        trace.add(
            "candidate_evidence_completed",
            candidate_id=candidate.candidate_id,
            status=status,
            reason=reason,
            claim_results=claim_results,
            answer_shape=answer_shape,
            hard_fail=any(
                is_fatal_hard_failure(record)
                for record in active_records
            ),
            unknown_claim_ids=[
                claim.claim_id
                for claim in candidate.claims
                if claim.claim_id not in claims_with_pass_evidence
            ],
        )

    @staticmethod
    def _repair_trace_changes(
        original,
        proposed,
        changed_claim_ids: list[str],
    ) -> list[dict[str, Any]]:
        old_claims = {claim.claim_id: claim for claim in original.claims}
        new_claims = {claim.claim_id: claim for claim in proposed.claims}
        return [
            {
                "claim_id": claim_id,
                "before": {
                    "statement": old_claims[claim_id].statement,
                    "depends_on": list(old_claims[claim_id].depends_on),
                    "check_type": old_claims[claim_id].check_type,
                    "importance": old_claims[claim_id].importance,
                },
                "after": {
                    "statement": new_claims[claim_id].statement,
                    "depends_on": list(new_claims[claim_id].depends_on),
                    "check_type": new_claims[claim_id].check_type,
                    "importance": new_claims[claim_id].importance,
                },
            }
            for claim_id in changed_claim_ids
            if claim_id in old_claims and claim_id in new_claims
        ]

    @staticmethod
    def _repair_completion_score(
        candidate,
        decision,
        evidence,
    ) -> tuple[int, int, int]:
        own_active = [
            record
            for record in evidence
            if record.candidate_id == candidate.candidate_id
            and record.transaction_status == "active"
        ]
        fatal_failures = sum(
            is_fatal_hard_failure(record)
            for record in own_active
        )
        verifier_adverse = sum(
            record.evidence_type == "llm:VerifierSkeptic"
            and record.status in {"fail", "unknown"}
            for record in own_active
        )
        return (
            fatal_failures,
            len(decision.unresolved_obligation_ids)
            + len(decision.failed_obligation_ids),
            verifier_adverse,
        )

    @staticmethod
    def _lemma_eligibility(session, candidates) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        if session.route_plan.risk_level != "high":
            reasons.append("risk_not_high")
        if session.problem_ir.problem_type not in {"proof", "derivation"}:
            reasons.append("problem_not_proof_or_derivation")
        claim_ids = {
            claim.claim_id
            for candidate in candidates
            for claim in candidate.claims
        }
        depths: dict[str, int] = {}
        for _ in range(len(claim_ids) + 1):
            changed = False
            for candidate in candidates:
                for claim in candidate.claims:
                    dependency_depths = [
                        depths.get(dependency, 0)
                        for dependency in claim.depends_on
                        if dependency in claim_ids
                    ]
                    depth = 1 + max(dependency_depths, default=0)
                    if depth > depths.get(claim.claim_id, 0):
                        depths[claim.claim_id] = depth
                        changed = True
            if not changed:
                break
        if max(depths.values(), default=0) < 3:
            reasons.append("claim_dependency_chain_too_shallow")
        semantic_pass_claim_ids = {
            record.claim_id
            for record in session.evidence
            if record.claim_id is not None
            and record.transaction_status == "active"
            and record.status == "pass"
            and record.strength == "hard"
            and record.capability
            not in {
                "none",
                "syntax.latex_brace_balance",
                "syntax.restricted_parse",
                "answer.shape",
            }
        }
        if not semantic_pass_claim_ids:
            reasons.append("no_semantically_verified_local_claim")
        return not reasons, reasons or ["all_lemma_preconditions_satisfied"]

    @staticmethod
    def _candidate_final_states(
        session,
        viable,
        selected_candidate_id: str,
        generation_failures,
        expanded_precheck_rejections: dict[str, list[str]],
    ) -> list[dict[str, Any]]:
        viable_ids = {candidate.candidate_id for candidate in viable}
        states: list[dict[str, Any]] = []
        for candidate in session.candidates:
            hard_failures = [
                record.evidence_id
                for record in session.evidence
                if record.candidate_id == candidate.candidate_id
                and is_fatal_hard_failure(record)
            ]
            reasons = list(
                expanded_precheck_rejections.get(candidate.candidate_id, [])
            )
            if hard_failures:
                reasons.append("hard_evidence_failure")
            if candidate.candidate_id == selected_candidate_id:
                status = "selected"
                reasons.append("arbitration_selected")
            elif candidate.candidate_id in viable_ids:
                status = "viable_not_selected"
                reasons.append("arbitration_not_selected")
            else:
                status = "rejected"
                if not reasons:
                    reasons.append("superseded_or_not_viable")
            states.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "version": candidate.version,
                    "status": status,
                    "reason_codes": sorted(set(reasons)),
                    "hard_failure_evidence_ids": hard_failures,
                    "claims": [
                        {
                            "claim_id": claim.claim_id,
                            "depends_on": list(claim.depends_on),
                            "status": claim.status,
                            "verification_state": claim.verification_state,
                        }
                        for claim in candidate.claims
                    ],
                    "proof_obligations": [
                        obligation.to_dict()
                        for obligation in session.proof_obligations.get(
                            candidate.candidate_id,
                            [],
                        )
                    ],
                }
            )
        states.extend(
            {
                "candidate_id": failure.candidate_id,
                "version": 0,
                "status": "generation_failed",
                "reason_codes": [failure.reason],
                "hard_failure_evidence_ids": [],
                "claims": [],
                "proof_obligations": [],
            }
            for failure in generation_failures
            if all(
                state["candidate_id"] != failure.candidate_id
                for state in states
            )
        )
        return states

    @staticmethod
    def _arbitration_rejections(
        session,
        viable,
        expanded_precheck_rejections: dict[str, list[str]],
    ) -> list[dict[str, Any]]:
        viable_ids = {candidate.candidate_id for candidate in viable}
        rejected = []
        for candidate in session.candidates:
            if candidate.candidate_id in viable_ids:
                continue
            reasons = list(
                expanded_precheck_rejections.get(candidate.candidate_id, [])
            )
            if any(
                record.candidate_id == candidate.candidate_id
                and is_fatal_hard_failure(record)
                for record in session.evidence
            ):
                reasons.append("hard_evidence_failure")
            if not reasons:
                reasons.append("not_viable_after_verification")
            rejected.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "reason_codes": sorted(set(reasons)),
                }
            )
        return rejected

    @staticmethod
    def _close_trace_invariants(trace: TraceBuilder) -> None:
        events = trace.internal_events
        starts = {
            str(event.get("candidate_id", ""))
            for event in events
            if event.get("event") == "candidate_generation_started"
        }
        success_events = {
            str(event.get("candidate_id", "")): event
            for event in events
            if event.get("event") == "candidate_generated"
        }
        terminal_ids = {
            str(event.get("candidate_id", ""))
            for event in events
            if event.get("event")
            in {"candidate_generated", "candidate_generation_failed"}
        }
        for candidate_id in sorted(starts - terminal_ids):
            trace.add(
                "candidate_generation_failed",
                **candidate_failure_trace_payload(
                    candidate_id,
                    "run_terminated_before_generation_terminal",
                ),
            )
        evidence_ids = {
            str(event.get("candidate_id", ""))
            for event in events
            if event.get("event") == "candidate_evidence_completed"
        }
        for candidate_id in sorted(set(success_events) - evidence_ids):
            content = success_events[candidate_id].get("content", {})
            claims = content.get("claims", []) if isinstance(content, dict) else []
            trace.add(
                "candidate_evidence_completed",
                candidate_id=candidate_id,
                status="skipped",
                reason="run_terminated_before_evidence",
                claim_results=[],
                answer_shape={"status": "skipped", "strength": "none"},
                hard_fail=False,
                unknown_claim_ids=[
                    str(claim.get("claim_id", ""))
                    for claim in claims
                    if isinstance(claim, dict) and claim.get("claim_id")
                ],
            )


def _tool_outcome_reason(status: str, summary: str) -> str:
    normalized_status = str(status).strip().lower()
    normalized_summary = str(summary).strip().lower()
    if normalized_status in {"pass", "fail", "error"}:
        return normalized_status
    if "timed out" in normalized_summary or "timeout" in normalized_summary:
        return "timeout"
    if any(
        marker in normalized_summary
        for marker in ("parse", "unparseable", "invalid expression")
    ):
        return "parse_unknown"
    if any(
        marker in normalized_summary
        for marker in ("domain", "assumption", "counterexample", "sample")
    ):
        return "domain_unknown"
    return "parse_unknown"
