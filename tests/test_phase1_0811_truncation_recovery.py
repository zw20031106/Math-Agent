from __future__ import annotations

import json

import pytest

from mathforge.agents.router_planner import RouterPlanner
from mathforge.agents.solver import PrimarySolver, SolverExecutor, SolverRequest
from mathforge.harness.budget import CallBudget
from mathforge.harness.provider import (
    ModelCallGate,
    OfficialClientProvider,
    _looks_truncated,
)
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.parsing.solution_parser import (
    SolutionParser,
    candidate_response_validation,
)


@pytest.mark.parametrize(
    ("response", "maximum", "observed", "expected"),
    [
        ("", 100, 0, "truncated"),
        ("x" * 95, 100, 95, "complete"),
        ('{"answer":"2"', 100, 4, "truncated"),
        ("<think>unfinished", 100, 4, "truncated"),
        ("The answer continues", 100, 4, "complete"),
        ('{"answer":"2"}', 100, 4, "complete"),
    ],
)
def test_string_only_provider_infers_truncation(
    response: str,
    maximum: int,
    observed: int,
    expected: bool,
) -> None:
    assert _looks_truncated(response, maximum, observed) == expected


def test_provider_records_inferred_finish_reason() -> None:
    class Client:
        def chat(self, **_kwargs):
            return '{"answer":"2"'

    budget = CallBudget(1)
    budget.consume(stage="primary")
    response = OfficialClientProvider(Client(), ModelCallGate(1)).chat(
        messages=[{"role": "user", "content": "compute"}],
        temperature=0.0,
        max_tokens=128,
        budget=budget,
        stage="primary",
    )

    assert response.output_budget_exceeded is True
    assert response.finish_reason == "length_inferred"
    assert budget.model_call_records[0]["response_truncated"] is True


def test_truncated_prefix_with_answer_is_degraded_not_fatal() -> None:
    candidate = SolutionParser().parse(
        '{"final_answer":"2",',
        candidate_id="truncated",
        role="PrimarySolver",
        answer_type="integer",
        planned_method_family="direct-deduction",
    )

    assert candidate.final_answer == "2"
    assert candidate.degraded is True
    assert candidate_response_validation(candidate) == (
        "candidate_json_incomplete",
        False,
    )


def test_truncated_autonomous_turn_salvages_without_retry() -> None:
    class Client:
        def __init__(self) -> None:
            self.calls = 0

        def chat(self, **_kwargs):
            self.calls += 1
            return '{"result_payload":{"answer":"4","check":"2+2=4"'

    client = Client()
    budget = CallBudget(2)
    turn = _execute_autonomous(client, budget)

    assert turn.candidate is not None
    assert turn.candidate.final_answer == "4"
    assert turn.candidate.degraded is True
    assert client.calls == 1
    assert budget.retry_count == 0


def test_truncated_autonomous_turn_uses_answer_only_retry() -> None:
    class Client:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def chat(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return "<think>unfinished reasoning"
            return r"\boxed{4}"

    client = Client()
    budget = CallBudget(3)
    turn = _execute_autonomous(client, budget)

    assert turn.candidate is not None
    assert turn.candidate.final_answer == "4"
    assert turn.candidate.degraded is True
    assert client.calls[1]["max_tokens"] == 2048
    assert "Output only the exact final answer" in client.calls[1]["messages"][0]["content"]
    assert budget.to_dict()["retry_count"] == 1
    assert budget.to_dict()["retry_reasons"] == {"truncated_answer_only": 1}


def _execute_autonomous(client, budget: CallBudget):
    problem = ProblemParser().parse("Compute 2+2.")
    route = RouterPlanner().plan(problem)
    return SolverExecutor(
        OfficialClientProvider(client, ModelCallGate(1)),
        SolutionParser(),
    ).execute_autonomous_candidate(
        PrimarySolver(),
        SolverRequest(
            "truncation-case",
            problem,
            route,
            "",
            route.method_families[0],
        ),
        budget,
        temperature=0.0,
        max_tokens=0,
    )
