from __future__ import annotations

from mathforge.agents.finalizer import LLMFinalizer
from mathforge.harness.budget import CallBudget
from mathforge.harness.provider import ModelCallGate, OfficialClientProvider
from mathforge.harness.schemas import CandidateSolution
from mathforge.output.deterministic_formatter import DeterministicFormatter
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.parsing.solution_parser import SolutionParser


class FinalizerClient:
    def __init__(self, answer: str) -> None:
        self.answer = answer

    def chat(self, *, messages, temperature, max_tokens):
        del messages, temperature, max_tokens
        return (
            '{"method":"presentation","solution_text":"Polished proof",'
            f'"final_answer":"{self.answer}"}}'
        )


def _run(answer: str):
    problem = ProblemParser().parse("证明结论")
    candidate = CandidateSolution(
        "c", "PrimarySolver", "direct", "42", "text", solution_text="Proof"
    )
    provider = OfficialClientProvider(FinalizerClient(answer), ModelCallGate(1))
    return LLMFinalizer(provider, SolutionParser(), DeterministicFormatter()).finalize(
        problem,
        candidate,
        "Proof\n\nFinal answer: 42",
        CallBudget(1),
        max_tokens=100,
    )


def test_finalizer_accepts_only_exact_answer_preserving_output():
    accepted = _run("42")
    assert accepted.used_llm
    assert accepted.text.endswith("42")
    rejected = _run("43")
    assert not rejected.used_llm
    assert rejected.text.endswith("42")
