from __future__ import annotations

from typing import Any
from dataclasses import replace
from time import perf_counter

from mathforge.agents.registry import PromptContractLoader, SkillRegistry
from mathforge.agents.router_planner import RouterPlanner
from mathforge.config import HarnessConfig, load_competition_config
from mathforge.harness.allocation import CallAllocationPlan
from mathforge.harness.budget import CallBudget
from mathforge.harness.debug import DebugSink, sanitized_failure_record
from mathforge.harness.errors import BudgetExceeded, classify_failure
from mathforge.harness.fallback import FallbackSolver
from mathforge.harness.fingerprints import request_fingerprint
from mathforge.harness.context_budget import ModelContextBudget
from mathforge.harness.metrics import collect_run_metrics
from mathforge.agents.solver import PrimarySolver, SolverExecutor, SolverRequest
from mathforge.harness.orchestration import (
    BranchFailure,
    CandidateOrchestrator,
    candidate_failure_trace_payload,
    candidate_trace_payload,
    public_candidate_content,
)
from mathforge.harness.provider import ModelCallGate, OfficialClientProvider
from mathforge.harness.session import create_session
from mathforge.harness.state import RuntimePhase
from mathforge.harness.trace import TraceBuilder
from mathforge.output.answer_validator import AnswerValidator
from mathforge.output.deterministic_formatter import DeterministicFormatter
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.parsing.solution_parser import SolutionParser
from mathforge.tools.executor import ToolExecutor
from mathforge.verification.evidence import EvidenceLedger
from mathforge.verification.arbitration import ArbitrationPolicy
from mathforge.verification.proof_obligations import ProofObligationEngine
from mathforge.context.errors import ContextBudgetExceeded
from mathforge.context.role_views import RoleContextFactory
from mathforge.memory.blackboard import MemoryBlackboard
from mathforge.harness.lemma_loop import VerifiedLemmaLoop
from mathforge.model_identity import ModelIdentity
from mathforge.retrieval.retriever import Retriever
from mathforge.provenance import build_run_provenance
from mathforge.verification.evidence import ClaimEvidenceVerifier
from mathforge.agents.repair import RepairAgent
from mathforge.harness.repair import ClaimRepairService
from mathforge.agents.finalizer import LLMFinalizer
from mathforge.agents.verifier import VerifierSkepticAgent
from mathforge.verification.completion import ProofCompletionGate


_ROLE_CONTRACT_DIRECTORIES = {
    "RouterPlanner": "router_planner",
    "PrimarySolver": "primary_solver",
    "AlternativeSolver": "alternative_solver",
    "LemmaCurator": "lemma_curator",
    "VerifierSkeptic": "verifier_skeptic",
    "RepairAgent": "repair",
    "LLMFinalizer": "finalizer",
}

_PUBLIC_METADATA_KEYS = (
    "idx",
    "benchmark_nonce",
    "label",
    "labels",
    "benchmark_label",
    "case_id",
    "split",
)


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
    ) -> None:
        self._config = config or load_competition_config()
        self._debug_sink = debug_sink
        self._context_budget = ModelContextBudget(
            context_window_tokens=self._config.model_context_window_tokens,
            safety_margin_tokens=self._config.context_safety_margin_tokens,
        )
        gate = ModelCallGate(self._config.model_max_concurrency)
        self._provider = OfficialClientProvider(
            client,
            gate,
            self._context_budget,
        )
        self._fallback = FallbackSolver()
        self._problem_parser = ProblemParser()
        self._solution_parser = SolutionParser()
        self._answer_validator = AnswerValidator()
        self._formatter = DeterministicFormatter()
        self._contracts = PromptContractLoader()
        self._role_contexts = RoleContextFactory()
        self._router = RouterPlanner(contracts=self._contracts)
        self._skills = SkillRegistry()
        self._solver_executor = SolverExecutor(self._provider, self._solution_parser)
        self._candidate_orchestrator = CandidateOrchestrator(
            self._solver_executor,
            self._contracts,
        )
        self._tool_executor = ToolExecutor(use_mcp=self._config.use_mcp)
        self._obligation_engine = ProofObligationEngine()
        self._arbitration = ArbitrationPolicy(self._tool_executor)
        self._lemma_loop = VerifiedLemmaLoop()
        self._retriever = Retriever()
        self._claim_verifier = ClaimEvidenceVerifier(self._tool_executor)
        self._repair_agent = RepairAgent(
            self._provider,
            self._solution_parser,
            self._contracts,
        )
        self._finalizer = LLMFinalizer(
            self._provider,
            self._solution_parser,
            self._formatter,
            self._contracts,
        )
        self._verifier_agent = VerifierSkepticAgent(self._provider, self._contracts)
        self._proof_completion_gate = ProofCompletionGate()
        self._run_provenance = build_run_provenance(
            self._config,
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
            "rag_hash": self._retriever.fingerprint,
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
            CallBudget(
                max_calls=self._config.max_model_calls,
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
            ),
            raw_context_max_chars=self._config.raw_context_max_chars,
        )
        fingerprint_nonce = str(safe_metadata.get("benchmark_nonce", session.session_id))
        run_fingerprint = request_fingerprint(normalized_problem, fingerprint_nonce)
        trace = TraceBuilder(
            session.trace_events,
            max_chars=self._config.trace_max_chars,
            max_events=self._config.trace_max_events,
            redacted_values=(
                [fingerprint_nonce]
                if "benchmark_nonce" in safe_metadata
                else []
            ),
        )
        trace.add(
            "session_started",
            session_id=session.session_id,
            request_fingerprint=run_fingerprint,
            **self._provenance,
        )
        outcome = "fallback"
        error_code = ""
        failure: Exception | None = None
        failed_phase = RuntimePhase.CREATED

        try:
            session.budget.ensure_stage("problem_parser")
            session.problem_ir = self._problem_parser.parse(normalized_problem)
            session.problem_ir.validate()
            blackboard = MemoryBlackboard(session.working_memory)
            if self._config.enable_memory:
                blackboard.publish(
                    "System",
                    "raw",
                    {"metadata": safe_metadata},
                )
            trace.add(
                "problem_parsed",
                problem_type=session.problem_ir.problem_type,
                answer_type=session.problem_ir.answer_type,
                assumptions=session.problem_ir.assumptions,
                domains=session.problem_ir.domains,
                risk_flags=session.problem_ir.risk_flags,
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
            router_unreachable = (
                router_enabled
                and self._config.max_model_calls - session.budget.used_calls
                <= 1 + int(potential_verifier)
            )
            if router_unreachable:
                router_enabled = False
            try:
                router_context = self._build_role_context(
                    session,
                    blackboard,
                    trace,
                    role="RouterPlanner",
                )
            except (ContextBudgetExceeded, BudgetExceeded):
                router_enabled = False
            session.route_plan = self._router.plan(
                session.problem_ir,
                llm_chat=(
                    (
                        lambda **kwargs: self._provider.chat(
                            budget=session.budget,
                            stage="router",
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
                            optional=True,
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
            allocation = CallAllocationPlan.build(
                max_calls=self._config.max_model_calls,
                router_calls=session.budget.used_calls,
                candidate_count=session.route_plan.candidate_count,
                verifier_required=verifier_required,
                repair_requested=(
                    self._config.enable_repair
                    and self._config.enable_evidence
                    and session.budget.deadline.exploration_allowed()
                ),
                lemma_requested=(
                    self._config.enable_lemma_loop
                    and session.route_plan.use_lemma_loop
                ),
                finalizer_requested=(
                    self._config.enable_finalizer
                    and session.route_plan.use_llm_finalizer
                ),
            )
            session.budget.set_allocation_plan(allocation)
            unreachable = list(allocation.unreachable_by_budget)
            if router_unreachable:
                unreachable.insert(0, "router")
            session.route_plan = replace(
                session.route_plan,
                candidate_count=1 + allocation.alternatives,
                use_lemma_loop=(
                    session.route_plan.use_lemma_loop
                    and allocation.lemma_reserve > 0
                ),
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
            skill_context = (
                self._skills.compose(
                    session.route_plan.selected_skills,
                    self._config.skill_char_budget,
                )
                if self._config.enable_skills
                else ""
            )
            if (
                session.route_plan.use_rag
                and session.budget.deadline.optional_work_allowed()
            ):
                session.budget.ensure_stage("rag", optional=True)
                retrieval_result = self._retriever.search_with_status(
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
                if cards:
                    rag_context = "\n\n".join(
                        f"## Reviewed knowledge: {card.title}\n{card.statement}\n"
                        f"Conditions: {', '.join(card.preconditions) or 'none'}\n"
                        f"Source: {card.source_ref} @ {card.source_version}"
                        for card in cards
                    )
                    skill_context = f"{skill_context}\n\n{rag_context}"[: self._config.skill_char_budget]
                trace.add(
                    "retrieval_completed",
                    status=retrieval_status,
                    card_ids=[card.id for card in cards],
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
            )
            skill_manifest = {
                item["name"]: item for item in self._skills.manifest
            }
            trace.add(
                "skills_selected",
                skills=[
                    {
                        "name": name,
                        "version": skill_manifest.get(name, {}).get(
                            "version",
                            "unknown",
                        ),
                        "role": "PrimarySolver",
                        "reason": (
                            "selected by deterministic route for "
                            f"{session.route_plan.primary_subject}"
                        ),
                    }
                    for name in (
                        session.route_plan.selected_skills
                        if self._config.enable_skills
                        else []
                    )
                ],
                skill_fingerprint=self._skills.fingerprint,
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
            fanout = self._candidate_orchestrator.fanout(
                session.problem_ir,
                session.route_plan,
                skill_context,
                session.budget,
                temperature=self._config.primary_temperature,
                max_tokens=self._config.primary_max_tokens,
                context_views=solver_contexts,
                event_callback=trace.add,
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
            if session.budget.must_finalize():
                for candidate in fanout.candidates:
                    self._trace_candidate_evidence(
                        trace,
                        candidate,
                        [],
                        status="skipped",
                        reason="deadline_finalize",
                    )
                trace.add("deadline_finalize", stage="after_fanout")
                raise RuntimeError("deterministic finalize reserve reached")
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
            tool_results = []
            if self._config.enable_tools:
                for item in fanout.candidates:
                    result, _ = self._run_answer_type_check(session, item, ledger)
                    tool_results.append(
                        {
                            "candidate_id": item.candidate_id,
                            "status": result.status,
                            "outcome_reason": _tool_outcome_reason(
                                result.status,
                                result.summary,
                            ),
                        }
                    )
                    if self._config.enable_evidence:
                        claim_records = self._claim_verifier.verify(
                            item,
                            ledger,
                            domains=session.problem_ir.domains,
                            assumptions=session.problem_ir.assumptions,
                            budget=session.budget,
                        )
                        tool_results.extend(
                            {
                                "candidate_id": item.candidate_id,
                                "claim_id": record.claim_id,
                                "status": record.status,
                                "outcome_reason": _tool_outcome_reason(
                                    record.status,
                                    record.description,
                                ),
                            }
                            for record in claim_records
                        )
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
                        "completed"
                        if evidence_checks_enabled
                        else "skipped"
                    ),
                    reason=(
                        "evidence_completed"
                        if evidence_checks_enabled
                        else "evidence_checks_disabled"
                    ),
                )
            active_candidates = list(fanout.candidates)
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
            if (
                self._config.enable_repair
                and self._config.enable_evidence
                and allocation.repair_reserve > 0
                and session.budget.deadline.exploration_allowed()
            ):
                repair_service = ClaimRepairService()
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
                active_candidates = repaired_candidates
            viable = (
                [
                    item
                    for item in active_candidates
                    if not ledger.has_hard_fail(item.candidate_id)
                ]
                if self._config.enable_evidence
                else list(active_candidates)
            )
            trace.add(
                "hard_evidence_gate",
                accepted=[item.candidate_id for item in viable],
                rejected=[
                    item.candidate_id for item in fanout.candidates if item not in viable
                ],
            )
            if not viable:
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
                    session.proof_obligations[item.candidate_id] = self._obligation_engine.generate(
                        session.problem_ir, item
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
                RuntimePhase.VERIFIED,
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
                    skill_context,
                ),
            )
            session.lemmas.extend(lemma_result.lemmas)
            session.rounds.extend(lemma_result.rounds)
            session.candidates.extend(lemma_result.generated_candidates)
            self._transition(
                session,
                trace,
                RuntimePhase.VERIFIED,
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
                    expanded.validate()
                    session.budget.record_claims(len(expanded.claims))
                except (BudgetExceeded, TypeError, ValueError):
                    rejection_codes.append("schema_or_claim_budget")
                rejection_codes.extend(
                    self._answer_validator.validate(
                        expanded,
                        session.problem_ir,
                    )
                )
                if not rejection_codes and self._config.enable_tools:
                    expanded_result, _ = self._run_answer_type_check(
                        session,
                        expanded,
                        ledger,
                    )
                    if (
                        expanded_result.status == "fail"
                        and expanded_result.strength == "hard"
                    ):
                        rejection_codes.append("answer_type_hard_fail")
                if (
                    not rejection_codes
                    and self._config.enable_tools
                    and self._config.enable_evidence
                ):
                    self._claim_verifier.verify(
                        expanded,
                        ledger,
                        domains=session.problem_ir.domains,
                        assumptions=session.problem_ir.assumptions,
                        budget=session.budget,
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
                        self._obligation_engine.generate(
                            session.problem_ir,
                            expanded,
                        )
                    )
                viable.append(expanded)
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
            skeptic_reviewed: set[str] = set()
            if (
                self._config.enable_verifier
                and self._config.enable_evidence
                and session.route_plan.risk_level in {"medium", "high"}
                and required_obligations
                and session.budget.deadline.exploration_allowed()
            ):
                verifier_context = self._build_role_context(
                    session,
                    blackboard,
                    trace,
                    role="VerifierSkeptic",
                    candidates=viable,
                    evidence=[],
                )
                verifier_result = self._verifier_agent.review(
                    session.problem_ir,
                    viable,
                    session.proof_obligations,
                    session.budget,
                    max_tokens=self._config.primary_max_tokens,
                    context_view=verifier_context,
                )
                for finding in verifier_result.findings:
                    ledger.record_verifier_finding(
                        candidate_id=finding.candidate_id,
                        claim_id=finding.claim_id,
                        obligation_ids=finding.obligation_ids,
                        status=finding.status,
                        description=finding.description,
                    )
                    skeptic_reviewed.add(finding.candidate_id)
                trace.add(
                    "verifier_completed",
                    used_llm=verifier_result.used_llm,
                    finding_count=len(verifier_result.findings),
                    reviewed_candidates=sorted(skeptic_reviewed),
                    reason=verifier_result.reason,
                )
            self._transition(
                session,
                trace,
                RuntimePhase.LEMMA_EXPANDED,
                RuntimePhase.REVERIFIED,
                "expanded_candidates_reverified",
            )
            if (
                self._config.enable_proof_obligations
                and session.problem_ir.problem_type in {"proof", "derivation"}
            ):
                completion_decisions = [
                    self._proof_completion_gate.evaluate(
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
                trace.add(
                    "proof_completion_gate",
                    accepted=sorted(completed_ids),
                    rejected=[
                        {
                            "candidate_id": decision.candidate_id,
                            "status": decision.status,
                            "unresolved_obligation_ids": decision.unresolved_obligation_ids,
                            "failed_obligation_ids": decision.failed_obligation_ids,
                            "failed_claim_ids": decision.failed_claim_ids,
                        }
                        for decision in completion_decisions
                        if decision.status != "complete"
                    ],
                )
                viable = [item for item in viable if item.candidate_id in completed_ids]
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
            )
            if not viable:
                raise RuntimeError("no proof candidate passed completion gate")
            arbitration = self._arbitration.select(
                viable,
                session.evidence,
                session.proof_obligations,
                budget=session.budget,
                problem=session.problem_ir,
            )
            candidate = arbitration.selected
            rank_details = [rank.to_dict() for rank in arbitration.ranks]
            trace.add(
                "candidate_arbitrated",
                selected=candidate.candidate_id,
                ranking=[rank.candidate_id for rank in arbitration.ranks],
                rank_details=rank_details,
                viable_candidates=[item.candidate_id for item in viable],
                rejected_candidates=self._arbitration_rejections(
                    session,
                    viable,
                    expanded_precheck_rejections,
                ),
                selection_reason=(
                    "lowest lexicographic evidence rank; stable generation order "
                    "breaks exact ties"
                ),
                equivalence_clusters=arbitration.clusters,
                equivalence_unknown_pairs=arbitration.unknown_pairs,
                equivalence_disagreement_pairs=arbitration.disagreement_pairs,
                used_llm_arbiter=arbitration.used_llm_arbiter,
            )
            self._transition(
                session,
                trace,
                RuntimePhase.REVERIFIED,
                RuntimePhase.ARBITRATED,
                "candidate_selected",
            )
            validation_errors = self._answer_validator.validate(candidate, session.problem_ir)
            trace.add(
                "primary_completed",
                model_calls=session.budget.used_calls,
                estimated_tokens=session.budget.used_tokens,
            )
            if validation_errors:
                trace.add("answer_validation_warning", codes=validation_errors)
            final_response = self._formatter.format(candidate, session.problem_ir)
            if not final_response.strip():
                raise ValueError("empty formatted response")
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
                    finalization = self._finalizer.finalize(
                        session.problem_ir,
                        candidate,
                        final_response,
                        session.budget,
                        max_tokens=self._config.primary_max_tokens,
                        context_view=finalizer_context,
                    )
                    final_response = finalization.text
                    trace.add(
                        "finalization_completed",
                        used_llm=finalization.used_llm,
                        reason=finalization.reason,
                    )
            elif (
                self._config.enable_finalizer
                and session.route_plan.use_llm_finalizer
            ):
                trace.add(
                    "finalization_completed",
                    used_llm=False,
                    reason="soft_deadline",
                )
            final_response, final_count = self._validated_final_response(
                final_response
            )
            trace.add(
                "final_answer_selected",
                candidate_id=candidate.candidate_id,
                selection_reason=(
                    "selected by hard-evidence gate and lexicographic arbitration"
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
            failed_phase = session.phase
            error_code = classify_failure(error, failed_phase).value
            transition = session.transition(
                failed_phase,
                RuntimePhase.FAILED,
                reason=error_code,
            )
            trace.add("phase_transition", **transition)
            final_response = self._fallback.solve(normalized_problem)
            transition = session.transition(
                RuntimePhase.FAILED,
                RuntimePhase.FALLBACK_COMPLETED,
                reason="fallback_completed",
            )
            trace.add("phase_transition", **transition)
            trace.add(
                "fallback_used",
                reason=error_code,
                error_code=error_code,
                failed_phase=failed_phase.value,
            )

        self._close_trace_invariants(trace)
        final_count = self._context_budget.ensure_text_within_window(
            final_response
        )
        session.budget.record_final_response(
            final_count.tokens,
            final_count.counting_mode,
        )
        trace.add(
            "budget_summary",
            **session.budget.to_dict(),
            outcome=outcome,
        )
        trace.add(
            "run_completed",
            outcome=outcome,
            error_code=error_code,
            final_phase=session.phase.value,
        )
        metrics = collect_run_metrics(
            budget=session.budget,
            internal_events=trace.internal_events,
            session_id=session.session_id,
            request_fingerprint=run_fingerprint,
            outcome=outcome,
            final_phase=session.phase.value,
            error_code=error_code,
        )
        if failure is not None and self._debug_sink is not None:
            try:
                self._debug_sink.record(
                    sanitized_failure_record(
                        failure,
                        session_id=session.session_id,
                        phase=failed_phase.value,
                        error_code=error_code,
                        internal_events=trace.internal_events,
                    )
                )
            except Exception:
                pass
        return {
            "final_response": final_response,
            "trace": trace.build(final_response=final_response),
            "run_metrics": metrics.to_dict(),
            "provenance": self._run_provenance.to_dict(),
        }

    def _validated_final_response(self, text: str):
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
        try:
            view = self._role_contexts.build(
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
        return self._repair_agent.repair(
            session.problem_ir,
            candidate,
            affected_claim_ids,
            local_evidence,
            session.budget,
            max_tokens=self._config.primary_max_tokens,
            context_view=context_view,
        )

    def _run_answer_type_check(self, session, candidate, ledger: EvidenceLedger):
        arguments = {
            "answer": candidate.final_answer,
            "answer_type": session.problem_ir.answer_type,
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
        _, records = self._run_answer_type_check(session, candidate, ledger)
        records.extend(
            self._claim_verifier.verify(
                candidate,
                ledger,
                only_claim_ids=affected_claim_ids,
                domains=session.problem_ir.domains,
                assumptions=session.problem_ir.assumptions,
                budget=session.budget,
            )
        )
        return records

    def _expand_with_verified_lemmas(
        self,
        session,
        blackboard: MemoryBlackboard,
        trace: TraceBuilder,
        verified_lemmas,
        round_id: int,
        skill_context: str,
    ):
        lemma_context = "\n".join(
            f"- {lemma.statement} (conditions: {', '.join(lemma.conditions) or 'none'})"
            for lemma in verified_lemmas
        )
        request = SolverRequest(
            candidate_id=f"lemma-round-{round_id}",
            problem=session.problem_ir,
            route=session.route_plan,
            skill_context=(
                f"{skill_context}\n\nVerified problem-local lemmas:\n{lemma_context}"
            )[: self._config.skill_char_budget],
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
                record.status == "fail" and record.strength == "hard"
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
                "before": old_claims[claim_id].statement,
                "after": new_claims[claim_id].statement,
            }
            for claim_id in changed_claim_ids
            if claim_id in old_claims and claim_id in new_claims
        ]

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
                and record.transaction_status == "active"
                and record.status == "fail"
                and record.strength == "hard"
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
