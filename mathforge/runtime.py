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
            candidate = fanout.candidates[0]
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
