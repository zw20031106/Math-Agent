from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from math import ceil
from threading import Lock
from time import perf_counter, sleep

import pytest

from mathforge.agents.solver import SolverExecutor
from mathforge.config import HarnessConfig
from mathforge.harness.budget import CallBudget
from mathforge.harness.deadline import DeadlineController
from mathforge.harness.errors import BudgetExceeded
from mathforge.harness.orchestration import CandidateOrchestrator
from mathforge.harness.provider import ModelCallGate, OfficialClientProvider
from mathforge.harness.schemas import RoutePlan
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.parsing.solution_parser import SolutionParser
from mathforge.runtime import MathForgeHarness


class SlowClient:
    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.calls = 0
        self.roles: list[str] = []
        self._lock = Lock()

    def chat(self, *, messages, temperature, max_tokens):
        del temperature, max_tokens
        with self._lock:
            self.calls += 1
            self.roles.append(messages[0]["content"])
        sleep(self.delay)
        return json.dumps(
            {
                "method": "direct",
                "solution_text": "slow result",
                "final_answer": "1",
                "answer_type": "expression",
                "claims": [],
            }
        )


def _short_budget(max_calls: int = 2) -> CallBudget:
    return CallBudget(
        max_calls,
        soft_deadline_seconds=0.03,
        exploration_deadline_seconds=0.06,
        hard_deadline_seconds=0.1,
        deterministic_finalize_reserve_seconds=0.02,
        model_call_start_margin_seconds=0.0,
    )


def _short_config() -> HarnessConfig:
    return HarnessConfig(
        max_model_calls=2,
        model_max_concurrency=4,
        soft_deadline_seconds=0.03,
        exploration_deadline_seconds=0.06,
        hard_deadline_seconds=0.1,
        deterministic_finalize_reserve_seconds=0.02,
        model_call_start_margin_seconds=0.0,
        enable_router=False,
        enable_skills=False,
        enable_alternatives=True,
        enable_tools=False,
        enable_evidence=False,
        enable_proof_obligations=False,
        enable_verifier=False,
        enable_memory=False,
        enable_lemma_loop=False,
        enable_rag=False,
        enable_repair=False,
        enable_finalizer=False,
    )


def test_deadline_controller_reserves_finalize_time_and_closes_optional_work():
    now = [0.0]
    deadline = DeadlineController(
        soft_deadline_seconds=0.03,
        exploration_deadline_seconds=0.06,
        hard_deadline_seconds=0.1,
        deterministic_finalize_reserve_seconds=0.02,
        clock=lambda: now[0],
    )
    now[0] = 0.031
    assert not deadline.optional_work_allowed()
    assert not deadline.can_start_model_call(optional=True)
    assert deadline.can_start_model_call()
    now[0] = 0.081
    assert deadline.must_finalize()
    assert deadline.remaining_seconds() == pytest.approx(0.019)

    budget = _short_budget()
    budget.deadline._started_at -= 0.031
    with pytest.raises(BudgetExceeded):
        budget.consume(optional=True)


def test_model_start_margin_blocks_new_calls_but_allows_local_finalization():
    now = [0.0]
    deadline = DeadlineController(
        soft_deadline_seconds=1.0,
        exploration_deadline_seconds=1.0,
        hard_deadline_seconds=1.0,
        deterministic_finalize_reserve_seconds=0.1,
        model_call_start_margin_seconds=0.2,
        clock=lambda: now[0],
    )
    now[0] = 0.71
    assert deadline.can_start_stage()
    assert not deadline.can_start_model_call()
    assert not deadline.must_finalize()


def test_fanout_returns_without_waiting_for_slow_unfinished_branches():
    client = SlowClient(0.3)
    provider = OfficialClientProvider(client, ModelCallGate(2))
    orchestrator = CandidateOrchestrator(SolverExecutor(provider, SolutionParser()))
    route = RoutePlan(
        primary_subject="algebra",
        auxiliary_subject=None,
        problem_type="calculation",
        answer_type="expression",
        risk_level="medium",
        candidate_count=2,
    )
    budget = _short_budget()
    started = perf_counter()
    result = orchestrator.fanout(
        ProblemParser().parse("solve equation x=1"),
        route,
        "",
        budget,
        temperature=0.2,
        max_tokens=100,
    )
    elapsed = perf_counter() - started

    assert elapsed < 0.2
    assert result.candidates == []
    assert len(result.failures) == 2
    used_tokens = budget.used_tokens
    sleep(0.35)
    assert result.candidates == []
    assert budget.used_tokens == used_tokens == 0


def test_hard_deadline_returns_fallback_within_tolerance():
    started = perf_counter()
    result = MathForgeHarness(SlowClient(0.3), _short_config()).solve(
        "solve equation x=1",
        {},
    )
    elapsed = perf_counter() - started

    assert elapsed < 0.2
    assert result["final_response"].strip()
    assert result["trace"][-1]["event"] == "run_completed"
    assert any(event["event"] == "fallback_used" for event in result["trace"])
    fanout = next(
        event for event in result["trace"] if event["event"] == "candidate_fanout_completed"
    )
    assert fanout["failures"][0]["reason"] == "deadline_cutoff"


def test_soft_cutoff_disables_optional_runtime_stages_before_they_start():
    client = SlowClient(0.0)
    config = replace(
        _short_config(),
        max_model_calls=4,
        soft_deadline_seconds=0.000001,
        exploration_deadline_seconds=0.1,
        hard_deadline_seconds=0.2,
        enable_skills=True,
        enable_tools=True,
        enable_evidence=True,
        enable_rag=True,
        enable_repair=True,
        enable_finalizer=True,
    )
    result = MathForgeHarness(client, config).solve("Explain why x equals x", {})

    cutoff = next(
        event
        for event in result["trace"]
        if event["event"] == "deadline_finalize" and event["stage"] == "soft_cutoff"
    )
    assert cutoff["disabled"] == [
        "alternatives",
        "rag",
        "lemma",
        "repair",
        "finalizer",
    ]
    assert client.calls == 1
    assert client.roles[0].startswith("You are PrimarySolver")
    assert all(event["event"] != "retrieval_completed" for event in result["trace"])
    assert all(event["event"] != "finalization_completed" for event in result["trace"])


def test_eight_problem_slow_client_p95_and_returned_traces_are_stable():
    client = SlowClient(0.3)
    harness = MathForgeHarness(client, _short_config())

    def solve_one(index: int):
        started = perf_counter()
        result = harness.solve(f"solve equation x={index}", {"idx": index})
        return perf_counter() - started, result

    with ThreadPoolExecutor(max_workers=8) as pool:
        completed = list(pool.map(solve_one, range(8)))

    latencies = sorted(item[0] for item in completed)
    p95 = latencies[ceil(0.95 * len(latencies)) - 1]
    traces = [[dict(event) for event in item[1]["trace"]] for item in completed]
    session_ids = {
        next(event["session_id"] for event in trace if event["event"] == "session_started")
        for trace in traces
    }

    assert p95 < 0.2
    assert len(session_ids) == 8
    assert all(item[1]["trace"][-1]["event"] == "run_completed" for item in completed)
    assert all(
        any(event["event"] == "fallback_used" for event in item[1]["trace"])
        for item in completed
    )
    sleep(0.35)
    assert traces == [item[1]["trace"] for item in completed]
