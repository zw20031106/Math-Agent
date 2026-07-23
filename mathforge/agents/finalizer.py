from __future__ import annotations

from dataclasses import dataclass

from mathforge.agents.registry import PromptContractLoader
from mathforge.context.snapshots import RoleContextView
from mathforge.harness.budget import CallBudget
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

    def finalize(
        self,
        problem: ProblemIR,
        candidate: CandidateSolution,
        deterministic_text: str,
        budget: CallBudget,
        *,
        max_tokens: int,
        context_view: RoleContextView | None = None,
    ) -> FinalizationResult:
        try:
            budget.consume()
            selected = (
                f"Authorized finalizer context:\n{context_view.to_prompt_json()}"
                if context_view is not None
                else f"Verified selected solution:\n{candidate.solution_text}"
            )
            user = (
                f"Problem:\n{problem.normalized_problem}\n\n{selected}\n\n"
                f"Exact final answer (must not change): {candidate.final_answer}"
            )
            response = self._provider.chat(
                messages=self._contracts.messages(
                    "finalizer",
                    user,
                    (
                        "Improve exposition only. Do not introduce new conclusions or "
                        "assumptions. Preserve the exact final answer. Return CandidateSolution JSON."
                    ),
                ),
                temperature=0.0,
                max_tokens=max_tokens,
            )
            budget.record_tokens(max(1, len(response) // 4))
            finalized = self._parser.parse(
                response,
                candidate_id=f"{candidate.candidate_id}-final",
                role="LLMFinalizer",
                answer_type=candidate.answer_type,
            )
            if normalized_answer(finalized.final_answer) != normalized_answer(candidate.final_answer):
                return FinalizationResult(deterministic_text, False, "exact_answer_changed")
            finalized.final_answer = candidate.final_answer
            text = self._formatter.format(finalized, problem)
            if not text.strip():
                return FinalizationResult(deterministic_text, False, "empty_finalization")
            return FinalizationResult(text, True, "accepted")
        except Exception:
            return FinalizationResult(deterministic_text, False, "finalizer_unavailable")
