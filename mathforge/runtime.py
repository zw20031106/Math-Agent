from __future__ import annotations

from typing import Any

from mathforge.agents.registry import SkillRegistry
from mathforge.agents.router_planner import RouterPlanner
from mathforge.config import HarnessConfig
from mathforge.harness.budget import CallBudget
from mathforge.harness.fallback import FallbackSolver
from mathforge.agents.solver import SolverExecutor
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
from mathforge.context.assembler import ContextAssembler, RawContextStore
from mathforge.context.compressor import ContextCompressor
from mathforge.memory.blackboard import MemoryBlackboard
from mathforge.harness.lemma_loop import VerifiedLemmaLoop
from mathforge.retrieval.retriever import Retriever


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
        self._router = RouterPlanner()
        self._skills = SkillRegistry()
        self._candidate_orchestrator = CandidateOrchestrator(
            SolverExecutor(self._provider, self._solution_parser)
        )
        self._tool_executor = ToolExecutor(use_mcp=self._config.use_mcp)
        self._obligation_engine = ProofObligationEngine()
        self._arbitration = ArbitrationPolicy(self._tool_executor)
        self._context_compressor = ContextCompressor()
        self._lemma_loop = VerifiedLemmaLoop()
        self._retriever = Retriever()

    def solve(self, problem: str, metadata: dict) -> dict:
        normalized_problem = problem if isinstance(problem, str) else str(problem)
        safe_metadata = dict(metadata) if isinstance(metadata, dict) else {}
        session = create_session(
            normalized_problem,
            safe_metadata,
            CallBudget(max_calls=self._config.max_model_calls),
        )
        trace = TraceBuilder(session.trace_events)
        trace.add("session_started", session_id=session.session_id)

        try:
            session.problem_ir = self._problem_parser.parse(normalized_problem)
            blackboard = MemoryBlackboard(session.working_memory)
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
            session.route_plan = self._router.plan(
                session.problem_ir,
                llm_chat=self._provider.chat,
                consume_call=session.budget.consume,
            )
            skill_context = self._skills.compose(
                session.route_plan.selected_skills,
                self._config.skill_char_budget,
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
            )
            fanout = self._candidate_orchestrator.fanout(
                session.problem_ir,
                session.route_plan,
                skill_context,
                session.budget,
                temperature=self._config.primary_temperature,
                max_tokens=self._config.primary_max_tokens,
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
            for item in fanout.candidates:
                result = self._tool_executor.execute(
                    "answer_type_check",
                    {"answer": item.final_answer, "answer_type": session.problem_ir.answer_type},
                )
                ledger.record_tool_result(candidate_id=item.candidate_id, claim_id=None, result=result)
            viable = [
                item for item in fanout.candidates if not ledger.has_hard_fail(item.candidate_id)
            ]
            trace.add(
                "hard_evidence_gate",
                accepted=[item.candidate_id for item in viable],
                rejected=[
                    item.candidate_id for item in fanout.candidates if item not in viable
                ],
            )
            if not viable:
                raise RuntimeError("all candidates failed hard evidence")
            for item in viable:
                session.proof_obligations[item.candidate_id] = self._obligation_engine.generate(
                    session.problem_ir, item
                )
            lemma_result = self._lemma_loop.run(
                session.route_plan,
                viable,
                session.evidence,
                session.proof_obligations,
                session.lemma_memory,
            )
            session.lemmas.extend(lemma_result.lemmas)
            session.rounds.extend(lemma_result.rounds)
            if session.route_plan.risk_level == "high":
                trace.add(
                    "lemma_loop_completed",
                    rounds=len(lemma_result.rounds),
                    verified=[
                        lemma.lemma_id for lemma in lemma_result.lemmas if lemma.status == "verified"
                    ],
                    stop_reason=lemma_result.stop_reason,
                )
            arbitration = self._arbitration.select(
                viable,
                session.evidence,
                session.proof_obligations,
            )
            candidate = arbitration.selected
            context_assembler = ContextAssembler(
                RawContextStore(self._config.raw_context_max_chars)
            )
            snapshot = context_assembler.assemble(
                session.problem_ir,
                viable,
                session.evidence,
                session.proof_obligations,
                final_answer=candidate.final_answer,
            )
            final_view = self._context_compressor.compress(
                snapshot,
                role="LLMFinalizer",
                max_chars=self._config.raw_context_max_chars,
            )
            blackboard.publish(
                "System",
                "working",
                {"context_snapshot": final_view.to_dict()},
            )
            trace.add(
                "candidate_arbitrated",
                selected=candidate.candidate_id,
                ranking=[rank.candidate_id for rank in arbitration.ranks],
                equivalence_clusters=arbitration.clusters,
            )
            validation_errors = self._answer_validator.validate(candidate, session.problem_ir)
            trace.add("primary_completed", model_calls=session.budget.used_calls)
            if validation_errors:
                trace.add("answer_validation_warning", codes=validation_errors)
            final_response = self._formatter.format(candidate, session.problem_ir)
            if not final_response.strip():
                raise ValueError("empty formatted response")
        except Exception:  # The public contract requires a result on every path.
            final_response = self._fallback.solve(normalized_problem)
            trace.add("fallback_used", reason="primary_unavailable")

        return {
            "final_response": final_response,
            "trace": trace.build(),
        }
