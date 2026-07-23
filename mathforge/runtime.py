from __future__ import annotations

from typing import Any
from dataclasses import replace
from time import perf_counter

from mathforge.agents.registry import PromptContractLoader, SkillRegistry
from mathforge.agents.router_planner import RouterPlanner
from mathforge.config import HarnessConfig
from mathforge.harness.budget import CallBudget
from mathforge.harness.fallback import FallbackSolver
from mathforge.harness.fingerprints import request_fingerprint
from mathforge.agents.solver import PrimarySolver, SolverExecutor, SolverRequest
from mathforge.harness.orchestration import CandidateOrchestrator
from mathforge.harness.provider import ModelCallGate, OfficialClientProvider
from mathforge.harness.session import create_session
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
from mathforge.retrieval.retriever import Retriever
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


class MathForgeHarness:
    """Thread-safe facade over the injected official model client."""

    def __init__(self, client: Any, config: HarnessConfig | None = None) -> None:
        self._config = config or HarnessConfig.from_environment()
        gate = ModelCallGate(self._config.model_max_concurrency)
        self._provider = OfficialClientProvider(client, gate)
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

    def solve(self, problem: str, metadata: dict) -> dict:
        normalized_problem = problem if isinstance(problem, str) else str(problem)
        safe_metadata = dict(metadata) if isinstance(metadata, dict) else {}
        session = create_session(
            normalized_problem,
            safe_metadata,
            CallBudget(
                max_calls=self._config.max_model_calls,
                max_tokens=self._config.max_model_tokens,
                soft_deadline_seconds=self._config.soft_deadline_seconds,
                exploration_deadline_seconds=self._config.exploration_deadline_seconds,
                hard_deadline_seconds=self._config.hard_deadline_seconds,
            ),
        )
        trace = TraceBuilder(session.trace_events, max_chars=self._config.trace_max_chars)
        fingerprint_nonce = str(safe_metadata.get("benchmark_nonce", session.session_id))
        trace.add(
            "session_started",
            session_id=session.session_id,
            request_fingerprint=request_fingerprint(normalized_problem, fingerprint_nonce),
        )

        try:
            session.problem_ir = self._problem_parser.parse(normalized_problem)
            blackboard = MemoryBlackboard(session.working_memory)
            if self._config.enable_memory:
                blackboard.publish(
                    "System",
                    "raw",
                    {"problem": session.problem_ir.raw_problem, "metadata": safe_metadata},
                )
            trace.add(
                "problem_parsed",
                problem_type=session.problem_ir.problem_type,
                answer_type=session.problem_ir.answer_type,
            )
            router_context = None
            router_enabled = self._config.enable_router
            try:
                router_context = self._build_role_context(
                    session,
                    blackboard,
                    trace,
                    role="RouterPlanner",
                )
            except ContextBudgetExceeded:
                router_enabled = False
            session.route_plan = self._router.plan(
                session.problem_ir,
                llm_chat=self._provider.chat if router_enabled else None,
                consume_call=session.budget.consume if router_enabled else None,
                record_tokens=(
                    session.budget.record_tokens if router_enabled else None
                ),
                context_view=router_context,
            )
            if not self._config.enable_alternatives:
                session.route_plan = replace(session.route_plan, candidate_count=1)
            if (
                self._config.enable_verifier
                and self._config.enable_evidence
                and self._config.enable_proof_obligations
                and session.problem_ir.problem_type in {"proof", "derivation"}
            ):
                candidate_capacity = max(
                    1,
                    self._config.max_model_calls - session.budget.used_calls - 1,
                )
                session.route_plan = replace(
                    session.route_plan,
                    candidate_count=min(
                        session.route_plan.candidate_count,
                        candidate_capacity,
                    ),
                )
            if not self._config.enable_lemma_loop:
                session.route_plan = replace(session.route_plan, use_lemma_loop=False)
            if not self._config.enable_rag:
                session.route_plan = replace(session.route_plan, use_rag=False)
            if not session.budget.can_start_exploration() and session.route_plan.candidate_count > 1:
                session.route_plan = replace(
                    session.route_plan,
                    candidate_count=1,
                    max_reasoning_rounds=1,
                    use_lemma_loop=False,
                )
                trace.add("deadline_finalize", stage="before_fanout")
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
            if session.route_plan.use_rag:
                cards = self._retriever.retrieve(
                    session.problem_ir.normalized_problem,
                    subject=session.route_plan.primary_subject,
                    role="PrimarySolver",
                    top_k=3,
                )
                if cards:
                    rag_context = "\n\n".join(
                        f"## Reviewed knowledge: {card.title}\n{card.statement}\n"
                        f"Conditions: {', '.join(card.preconditions) or 'none'}\n"
                        f"Source: {card.source_ref}"
                        for card in cards
                    )
                    skill_context = f"{skill_context}\n\n{rag_context}"[: self._config.skill_char_budget]
                trace.add("retrieval_completed", card_ids=[card.id for card in cards])
            trace.add(
                "route_planned",
                primary_subject=session.route_plan.primary_subject,
                risk_level=session.route_plan.risk_level,
                selected_skills=session.route_plan.selected_skills,
                method_families=session.route_plan.method_families,
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
            fanout = self._candidate_orchestrator.fanout(
                session.problem_ir,
                session.route_plan,
                skill_context,
                session.budget,
                temperature=self._config.primary_temperature,
                max_tokens=self._config.primary_max_tokens,
                context_views=solver_contexts,
            )
            session.candidates.extend(fanout.candidates)
            trace.add(
                "candidate_fanout_completed",
                completed=[candidate.candidate_id for candidate in fanout.candidates],
                failed=[failure.candidate_id for failure in fanout.failures],
            )
            if not fanout.candidates:
                raise RuntimeError("all solver branches failed")
            ledger = EvidenceLedger(session.evidence)
            tool_results = []
            if self._config.enable_tools:
                for item in fanout.candidates:
                    result, _ = self._run_answer_type_check(session, item, ledger)
                    tool_results.append({"candidate_id": item.candidate_id, "status": result.status})
                    if self._config.enable_evidence:
                        claim_records = self._claim_verifier.verify(
                            item,
                            ledger,
                            domains=session.problem_ir.domains,
                            assumptions=session.problem_ir.assumptions,
                        )
                        tool_results.extend(
                            {
                                "candidate_id": item.candidate_id,
                                "claim_id": record.claim_id,
                                "status": record.status,
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
            active_candidates = list(fanout.candidates)
            if self._config.enable_repair and self._config.enable_evidence:
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
                    if repair_result.triggered:
                        trace.add(
                            "repair_completed",
                            candidate_id=item.candidate_id,
                            selected_candidate_id=repair_result.selected.candidate_id,
                            affected_claim_ids=repair_result.affected_claim_ids,
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
            if self._config.enable_proof_obligations:
                for item in viable:
                    session.proof_obligations[item.candidate_id] = self._obligation_engine.generate(
                        session.problem_ir, item
                    )
            unresolved_required = [
                obligation
                for item in viable
                for obligation in session.proof_obligations.get(item.candidate_id, [])
                if obligation.required and obligation.status != "satisfied"
            ]
            if (
                self._config.enable_verifier
                and self._config.enable_evidence
                and session.route_plan.risk_level in {"medium", "high"}
                and unresolved_required
            ):
                verifier_context = self._build_role_context(
                    session,
                    blackboard,
                    trace,
                    role="VerifierSkeptic",
                    candidates=viable,
                )
                verifier_result = self._verifier_agent.review(
                    session.problem_ir,
                    viable,
                    session.proof_obligations,
                    session.budget,
                    max_tokens=min(1536, self._config.primary_max_tokens),
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
                trace.add(
                    "verifier_completed",
                    used_llm=verifier_result.used_llm,
                    finding_count=len(verifier_result.findings),
                    reason=verifier_result.reason,
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
                    ledger,
                ),
            )
            session.lemmas.extend(lemma_result.lemmas)
            session.rounds.extend(lemma_result.rounds)
            session.candidates.extend(lemma_result.generated_candidates)
            for expanded in lemma_result.generated_candidates:
                if self._config.enable_tools:
                    expanded_result, _ = self._run_answer_type_check(
                        session, expanded, ledger
                    )
                    if (
                        self._config.enable_evidence
                        and expanded_result.status == "fail"
                        and expanded_result.strength == "hard"
                    ):
                        continue
                viable.append(expanded)
                if self._config.enable_proof_obligations:
                    session.proof_obligations[expanded.candidate_id] = (
                        self._obligation_engine.generate(session.problem_ir, expanded)
                    )
            if session.route_plan.risk_level == "high":
                trace.add(
                    "lemma_loop_completed",
                    rounds=len(lemma_result.rounds),
                    verified=[
                        lemma.lemma_id for lemma in lemma_result.lemmas if lemma.status == "verified"
                    ],
                    stop_reason=lemma_result.stop_reason,
                    error_rate=lemma_result.error_rate,
                    generated_candidates=[
                        item.candidate_id for item in lemma_result.generated_candidates
                    ],
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
                if not viable:
                    raise RuntimeError("no proof candidate passed completion gate")
            arbitration = self._arbitration.select(
                viable,
                session.evidence,
                session.proof_obligations,
            )
            candidate = arbitration.selected
            trace.add(
                "candidate_arbitrated",
                selected=candidate.candidate_id,
                ranking=[rank.candidate_id for rank in arbitration.ranks],
                equivalence_clusters=arbitration.clusters,
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
            if self._config.enable_finalizer and session.route_plan.use_llm_finalizer:
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
                        max_tokens=min(2048, self._config.primary_max_tokens),
                        context_view=finalizer_context,
                    )
                    final_response = finalization.text
                    trace.add(
                        "finalization_completed",
                        used_llm=finalization.used_llm,
                        reason=finalization.reason,
                    )
            trace.add(
                "budget_summary",
                model_calls=session.budget.used_calls,
                estimated_tokens=session.budget.used_tokens,
                outcome="primary",
            )
        except Exception:  # The public contract requires a result on every path.
            final_response = self._fallback.solve(normalized_problem)
            trace.add(
                "budget_summary",
                model_calls=session.budget.used_calls,
                estimated_tokens=session.budget.used_tokens,
                outcome="fallback",
            )
            trace.add("fallback_used", reason="primary_unavailable")

        return {
            "final_response": final_response,
            "trace": trace.build(),
        }

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
    ):
        role_directory = _ROLE_CONTRACT_DIRECTORIES[role]
        contract_budget = self._contracts.load(role_directory).max_context_chars
        view_budget = min(
            self._config.raw_context_max_chars,
            max(256, contract_budget // 2),
        )
        selected_candidates = (
            list(session.candidates) if candidates is None else list(candidates)
        )
        candidate_ids = {candidate.candidate_id for candidate in selected_candidates}
        selected_evidence = (
            [
                record
                for record in session.evidence
                if not candidate_ids or record.candidate_id in candidate_ids
            ]
            if evidence is None
            else list(evidence)
        )
        selected_obligations = {
            candidate_id: items
            for candidate_id, items in session.proof_obligations.items()
            if not candidate_ids or candidate_id in candidate_ids
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
            )
        except ContextBudgetExceeded as exc:
            trace.add(
                "context_budget_infeasible",
                role=role,
                max_chars=view_budget,
                reason=str(exc),
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
        started = perf_counter()
        result = self._tool_executor.execute("answer_type_check", arguments)
        duration_ms = (perf_counter() - started) * 1000
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
                    timeout_seconds=self._tool_executor.default_timeout,
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
        _, records = self._run_answer_type_check(session, candidate, ledger)
        records.extend(
            self._claim_verifier.verify(
                candidate,
                ledger,
                only_claim_ids=affected_claim_ids,
                domains=session.problem_ir.domains,
                assumptions=session.problem_ir.assumptions,
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
        ledger: EvidenceLedger,
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
            method_family=f"lemma-guided-{session.route_plan.primary_subject}",
            context_view=self._build_role_context(
                session,
                blackboard,
                trace,
                role="PrimarySolver",
                candidates=session.candidates,
            ),
        )
        candidate = self._solver_executor.execute(
            PrimarySolver(self._contracts),
            request,
            session.budget,
            temperature=self._config.primary_temperature,
            max_tokens=self._config.primary_max_tokens,
        )
        if self._config.enable_tools and self._config.enable_evidence:
            self._claim_verifier.verify(
                candidate,
                ledger,
                domains=session.problem_ir.domains,
                assumptions=session.problem_ir.assumptions,
            )
        return candidate
