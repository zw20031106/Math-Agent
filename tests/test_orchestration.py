from __future__ import annotations

from mathforge.agents.solver import SolverExecutor
from mathforge.harness.budget import CallBudget
from mathforge.harness.orchestration import CandidateOrchestrator
from mathforge.harness.provider import ModelCallGate, OfficialClientProvider
from mathforge.harness.schemas import RoutePlan
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.parsing.solution_parser import SolutionParser
from tests.fake_client import FakeClient


def _route(count: int = 2) -> RoutePlan:
    return RoutePlan(
        primary_subject="algebra",
        auxiliary_subject=None,
        problem_type="calculation",
        answer_type="expression",
        risk_level="medium",
        selected_skills=["algebra"],
        selected_tools=[],
        candidate_count=count,
    )


def test_fanout_is_parallel_stable_and_hides_primary_text():
    client = FakeClient(delay=0.02)
    provider = OfficialClientProvider(client, ModelCallGate(2))
    orchestrator = CandidateOrchestrator(SolverExecutor(provider, SolutionParser()))
    result = orchestrator.fanout(
        ProblemParser().parse("solve x+1=2"),
        _route(),
        "skill",
        CallBudget(2),
        temperature=0.2,
        max_tokens=4096,
    )
    assert [candidate.candidate_id for candidate in result.candidates] == [
        "primary-1",
        "alternative-1",
    ]
    assert client.max_active_calls == 2
    alternative_prompt = next(
        call["messages"][-1]["content"]
        for call in client.calls
        if call["messages"][0]["content"].startswith("You are AlternativeSolver")
    )
    assert "Required core method family: factorization-invariant" in alternative_prompt
    assert "Forbidden method families: substitution-elimination" in alternative_prompt
    assert "Solved independently" not in alternative_prompt
    assert result.candidates[0].planned_method_family == "substitution-elimination"
    assert result.candidates[1].planned_method_family == "factorization-invariant"
    assert result.candidates[1].is_method_duplicate is True


class OneBranchFailsClient(FakeClient):
    def chat(self, *, messages, temperature, max_tokens):
        if messages[0]["content"].startswith("You are AlternativeSolver"):
            raise RuntimeError("alternative failed")
        return super().chat(messages=messages, temperature=temperature, max_tokens=max_tokens)


def test_branch_failure_does_not_discard_primary():
    client = OneBranchFailsClient()
    provider = OfficialClientProvider(client, ModelCallGate(2))
    result = CandidateOrchestrator(SolverExecutor(provider, SolutionParser())).fanout(
        ProblemParser().parse("equation x=1"),
        _route(),
        "",
        CallBudget(2),
        temperature=0.2,
        max_tokens=4096,
    )
    assert [candidate.candidate_id for candidate in result.candidates] == ["primary-1"]
    assert result.failures[0].candidate_id == "alternative-1"
