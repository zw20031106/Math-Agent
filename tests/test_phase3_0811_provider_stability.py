from __future__ import annotations

from threading import Event, Thread
from time import sleep

import pytest

from mathforge.config import load_competition_config
from mathforge.harness.budget import CallBudget
from mathforge.harness.context_budget import ModelContextBudget, TokenCount
from mathforge.harness.deadline import DeadlineController
from mathforge.harness.errors import ModelCallRejected
from mathforge.harness.model_policy import feasible_queue_budget
from mathforge.harness.provider import ModelCallGate, OfficialClientProvider


def _deadline(seconds: float) -> DeadlineController:
    return DeadlineController(
        soft_deadline_seconds=seconds,
        exploration_deadline_seconds=seconds,
        hard_deadline_seconds=seconds,
        deterministic_finalize_reserve_seconds=min(0.005, seconds / 10),
        model_call_start_margin_seconds=0.0,
    )


def test_competition_stability_policy_matches_phase3_contract() -> None:
    config = load_competition_config()

    assert config.max_background_model_tails == 6
    assert {
        spec["minimum_start_window_seconds"]
        for spec in config.stage_execution_policy.values()
    } == {30.0}
    assert 0.0 < feasible_queue_budget("primary", 30.5, 60.0) <= 0.5


def test_provider_failure_circuit_is_isolated_by_case() -> None:
    gate = ModelCallGate(2)
    for _ in range(4):
        gate.record_provider_result(
            success=False,
            failure_code="provider_5xx",
            case_id="case-a",
        )

    assert gate.health_snapshot("case-a")["state"] == "circuit_open"
    assert gate.health_snapshot("case-b")["state"] == "healthy"
    with pytest.raises(ModelCallRejected) as rejected:
        gate.call(lambda: "blocked", case_id="case-a")
    assert rejected.value.code == "model_provider_circuit_open"
    assert gate.call(lambda: "ok", case_id="case-b") == "ok"


def test_tail_degradation_requires_more_than_half_physical_concurrency() -> None:
    release = Event()
    gate = ModelCallGate(6, max_background_tails=24)

    for index in range(4):
        with pytest.raises(ModelCallRejected):
            gate.call(
                lambda: (release.wait(1), "late")[1],
                case_id="case-a",
                deadline=_deadline(0.025),
                queue_budget_seconds=0.005,
                stage_timeout_seconds=0.01,
            )
        expected = "degraded" if index == 3 else "healthy"
        assert gate.health_snapshot("case-a")["state"] == expected

    assert gate.health_snapshot("case-b")["state"] == "healthy"
    release.set()
    for _ in range(100):
        if gate.health_snapshot("case-a")["active_tails"] == 0:
            break
        sleep(0.002)


def test_circuit_cooldown_allows_exactly_one_half_open_probe() -> None:
    now = [0.0]
    gate = ModelCallGate(
        2,
        circuit_cooldown_seconds=60.0,
        clock=lambda: now[0],
    )
    for _ in range(4):
        gate.record_provider_result(
            success=False,
            failure_code="provider_5xx",
            case_id="case-a",
        )
    now[0] = 61.0

    entered = Event()
    release = Event()
    results: list[str] = []

    def probe() -> None:
        results.append(
            gate.call(
                lambda: (entered.set(), release.wait(1), "recovered")[-1],
                case_id="case-a",
            )
        )
        gate.record_provider_result(success=True, case_id="case-a")

    worker = Thread(target=probe)
    worker.start()
    assert entered.wait(0.2)
    assert gate.health_snapshot("case-a")["state"] == "half_open"
    with pytest.raises(ModelCallRejected) as rejected:
        gate.call(lambda: "second probe", case_id="case-a")
    assert rejected.value.code == "model_provider_circuit_open"

    release.set()
    worker.join(0.5)
    assert results == ["recovered"]
    assert gate.health_snapshot("case-a")["state"] == "healthy"


class _FixedCounter:
    def count_messages(self, _messages) -> TokenCount:
        return TokenCount(10, "multilingual_estimate", "test", "test")

    def count_text(self, text: str) -> TokenCount:
        return TokenCount(len(text), "multilingual_estimate", "test", "test")


def test_completed_response_beyond_context_estimate_is_retained_with_warning() -> None:
    response = "x" * 60
    client = type("Client", (), {"chat": lambda self, **_: response})()
    budget = CallBudget(1)
    budget.consume(stage="primary")
    provider = OfficialClientProvider(
        client,
        ModelCallGate(1),
        ModelContextBudget(
            context_window_tokens=64,
            safety_margin_tokens=8,
            token_counter=_FixedCounter(),
        ),
    )

    observed = provider.chat(
        messages=[{"role": "user", "content": "solve"}],
        temperature=0.0,
        max_tokens=4,
        budget=budget,
        stage="primary",
    )

    assert observed == response
    assert budget.model_call_records[0]["context_window_warning"] == (
        "response_exceeded_estimate"
    )
