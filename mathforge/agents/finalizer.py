from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json

from mathforge.agents.prompt_compiler import PromptCompiler
from mathforge.agents.registry import PromptContractLoader
from mathforge.context.snapshots import RoleContextView
from mathforge.harness.budget import CallBudget
from mathforge.harness.errors import ModelResponseError
from mathforge.harness.provider import OfficialClientProvider
from mathforge.harness.schemas import CandidateSolution, ProblemIR
from mathforge.output.deterministic_formatter import DeterministicFormatter
from mathforge.parsing.solution_parser import SolutionParser
from mathforge.verification.equivalence import normalized_answer


@dataclass(frozen=True)
class FinalizationResult:
    text: str
    used_llm: bool
    reason: str


class LLMFinalizer:
    def __init__(
        self,
        provider: OfficialClientProvider,
        parser: SolutionParser,
        formatter: DeterministicFormatter,
        contracts: PromptContractLoader | None = None,
    ) -> None:
        self._provider = provider
        self._parser = parser
        self._formatter = formatter
        self._contracts = contracts or PromptContractLoader()
        self._compiler = PromptCompiler(self._contracts)

    def finalize(
        self,
        problem: ProblemIR,
        candidate: CandidateSolution,
        deterministic_text: str,
        budget: CallBudget,
        *,
        max_tokens: int,
        context_view: RoleContextView | None = None,
        skill_context: str = "",
    ) -> FinalizationResult:
        try:
            budget.consume(stage="finalizer", optional=True)
            selected = (
                f"Authorized finalizer context:\n{context_view.to_prompt_json()}"
                if context_view is not None
                else f"Verified selected solution:\n{candidate.solution_text}"
            )
            user = (
                f"Problem:\n{problem.normalized_problem}\n\n{selected}\n\n"
                f"Exact final answer (must not change): {candidate.final_answer}"
                + (
                    f"\n\nAuthorized skill guidance:\n{skill_context}"
                    if skill_context.strip()
                    else ""
                )
            )
            compilation = self._compiler.compile_role(
                "finalizer",
                user_content=user,
                runtime_instructions=(
                    "Normalize formatting only. Do not rewrite the public solution "
                    "or introduce new conclusions or assumptions. Preserve the "
                    "exact final answer. "
                    f"Host response mode is {problem.response_mode}. Return "
                    "only the compiled finalizer response object."
                ),
            )
            messages = compilation.messages
            budget.record_prompt_chars(
                sum(len(message["content"]) for message in messages)
            )
            response = self._provider.chat(
                messages=messages,
                temperature=0.0,
                max_tokens=PromptCompiler.bounded_output_tokens(
                    max_tokens,
                    compilation.max_output_tokens,
                ),
                budget=budget,
                stage="finalizer",
                turn_kind="finalizer",
                agent_id="LLMFinalizer",
            )
            if budget.deadline.must_finalize():
                return FinalizationResult(deterministic_text, False, "finalize_cutoff")
            budget.ensure_stage("solution_parser")
            try:
                payload = json.loads(str(response))
            except (TypeError, json.JSONDecodeError) as error:
                raise ModelResponseError("finalizer_schema_invalid") from error
            if not isinstance(payload, dict) or set(payload) != {
                "final_answer",
                "solution_text",
            }:
                return FinalizationResult(
                    deterministic_text,
                    False,
                    "verified_content_changed",
                )
            if not all(isinstance(payload[name], str) for name in payload):
                raise ModelResponseError("finalizer_schema_invalid")
            budget.record_model_response_validation(
                getattr(response, "model_call_index", None),
                "strict_finalizer_json",
                rejected=False,
            )
            if normalized_answer(payload["final_answer"]) != normalized_answer(candidate.final_answer):
                return FinalizationResult(deterministic_text, False, "exact_answer_changed")
            if self._normalize_text(payload["solution_text"]) != self._normalize_text(
                candidate.solution_text
            ):
                return FinalizationResult(
                    deterministic_text,
                    False,
                    "verified_content_changed",
                )
            finalized = deepcopy(candidate)
            finalized.solution_text = payload["solution_text"]
            finalized.final_answer = candidate.final_answer
            text = self._formatter.format(finalized, problem)
            if not text.strip():
                return FinalizationResult(deterministic_text, False, "empty_finalization")
            return FinalizationResult(text, True, "accepted")
        except Exception:
            return FinalizationResult(deterministic_text, False, "finalizer_unavailable")

    @staticmethod
    def _normalize_text(value: str) -> str:
        return " ".join(str(value).split())
