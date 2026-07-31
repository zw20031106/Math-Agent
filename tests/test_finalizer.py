from __future__ import annotations

import json
from pathlib import Path

import pytest

from mathforge.agents.finalizer import LLMFinalizer
from mathforge.config import HarnessConfig
from mathforge.harness.budget import CallBudget
from mathforge.harness.provider import ModelCallGate, OfficialClientProvider
from mathforge.harness.schemas import CandidateSolution, Claim, MethodStep
from mathforge.output.deterministic_formatter import DeterministicFormatter
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.parsing.solution_parser import SolutionParser


class FinalizerClient:
    def __init__(
        self,
        answer: str,
        solution_text: str,
        extra: dict | None = None,
    ) -> None:
        self.answer = answer
        self.solution_text = solution_text
        self.extra = dict(extra or {})

    def chat(self, *, messages, temperature, max_tokens):
        del messages, temperature, max_tokens
        return json.dumps(
            {
                "method": "direct",
                "method_steps": [
                    {
                        "step_id": "s1",
                        "kind": "conclusion",
                        "claim_ids": ["c1"],
                        "theorem": "",
                    }
                ],
                "solution_text": self.solution_text,
                "public_solution_steps": [self.solution_text],
                "final_answer": self.answer,
                "assumptions": [],
                "theorems": [],
                "claims": [
                    {
                        "claim_id": "c1",
                        "statement": "The verified result is 42.",
                        "depends_on": [],
                        "check_type": "reasoning",
                        "importance": "critical",
                    }
                ],
                "unresolved_obligations": [],
                **self.extra,
            }
        )


def _run(answer: str, solution_text: str = "Proof", extra: dict | None = None):
    problem = ProblemParser().parse("证明结论")
    candidate = CandidateSolution(
        "c",
        "PrimarySolver",
        "direct",
        "42",
        "text",
        claims=[
            Claim(
                "c1",
                "The verified result is 42.",
                check_type="reasoning",
                importance="critical",
                claim_kind="reasoning",
            )
        ],
        public_solution_steps=["Proof"],
        solution_text="Proof",
        method_steps=[MethodStep("s1", "conclusion", ["c1"])],
    )
    provider = OfficialClientProvider(
        FinalizerClient(answer, solution_text, extra),
        ModelCallGate(1),
    )
    return LLMFinalizer(provider, SolutionParser(), DeterministicFormatter()).finalize(
        problem,
        candidate,
        "Proof\n\nFinal answer: $42$",
        CallBudget(1),
        max_tokens=0,
    )


def test_finalizer_accepts_only_exact_answer_preserving_output():
    accepted = _run("42")
    assert accepted.used_llm
    assert accepted.text.endswith("Final answer: $42$")
    rejected = _run("43")
    assert not rejected.used_llm
    assert rejected.text.endswith("Final answer: $42$")


def test_finalizer_rolls_back_same_answer_with_changed_mathematical_content():
    result = _run("42", "False claim: one plus one equals three.")
    assert not result.used_llm
    assert result.reason == "verified_content_changed"
    assert result.text == "Proof\n\nFinal answer: $42$"


@pytest.mark.parametrize(
    ("solution_text", "extra"),
    [
        ("Proof with a new number 43.", None),
        (r"Proof with a new formula x^2=1.", None),
        ("Proof", {"assumptions": ["x > 0"]}),
        ("Proof", {"theorems": ["Invented theorem"]}),
        ("Proof", {"method": "different-method"}),
        ("Proof", {"public_solution_steps": ["Changed public proof."]}),
        ("Proof", {"unresolved_obligations": ["New open obligation"]}),
    ],
)
def test_finalizer_rolls_back_new_entities_assumptions_and_theorems(
    solution_text,
    extra,
):
    result = _run("42", solution_text, extra)
    assert not result.used_llm
    assert result.reason == "verified_content_changed"


def test_llm_finalizer_is_disabled_in_default_and_competition_configs():
    root = Path(__file__).resolve().parents[1]
    competition = json.loads(
        (root / "config" / "competition.json").read_text(encoding="utf-8")
    )
    assert HarnessConfig().enable_finalizer is False
    assert competition["enable_finalizer"] is False
