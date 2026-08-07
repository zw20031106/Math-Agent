from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Lock, Thread
from time import sleep

from mathforge.harness.budget import CallBudget
from mathforge.harness.model_policy import (
    feasible_queue_budget,
    stage_sequence_feasible,
    stage_sequence_reserve_seconds,
)
from mathforge.harness.priority_scheduler import PriorityCallScheduler
from mathforge.harness.provider import ModelCallGate, OfficialClientProvider
from mathforge.harness.session import create_session
from scripts.compare_capacity_profiles import compare


def _wait_for_queue(scheduler: PriorityCallScheduler, count: int) -> None:
    for _ in range(200):
        if scheduler.snapshot()["queued"] == count:
            return
        sleep(0.001)
    raise AssertionError(f"scheduler did not reach queue depth {count}")


def test_same_stage_waiters_are_admitted_round_robin_across_cases():
    scheduler = PriorityCallScheduler(1)
    assert scheduler.acquire("unallocated")
    order: list[str] = []

    def run(case_id: str) -> None:
        assert scheduler.acquire("primary", 0.5, case_id=case_id)
        order.append(case_id)
        scheduler.release()

    first_a = Thread(target=run, args=("case-a",))
    second_a = Thread(target=run, args=("case-a",))
    case_b = Thread(target=run, args=("case-b",))
    first_a.start()
    _wait_for_queue(scheduler, 1)
    second_a.start()
    _wait_for_queue(scheduler, 2)
    case_b.start()
    _wait_for_queue(scheduler, 3)
    scheduler.release()
    for thread in (first_a, second_a, case_b):
        thread.join(0.5)

    assert order == ["case-a", "case-b", "case-a"]


def test_verifier_does_not_preempt_unformed_alternative_without_aging():
    scheduler = PriorityCallScheduler(1)
    assert scheduler.acquire("unallocated")
    order: list[str] = []

    def run(stage: str) -> None:
        assert scheduler.acquire(stage, 0.5, case_id=stage)
        order.append(stage)
        scheduler.release()

    verifier = Thread(target=run, args=("verifier",))
    alternative = Thread(target=run, args=("alternative",))
    verifier.start()
    _wait_for_queue(scheduler, 1)
    alternative.start()
    _wait_for_queue(scheduler, 2)
    scheduler.release()
    verifier.join(0.5)
    alternative.join(0.5)

    assert order == ["alternative", "verifier"]


def test_stage_aging_eventually_promotes_an_old_waiter():
    now = [0.0]
    scheduler = PriorityCallScheduler(
        1,
        aging_interval_seconds=10.0,
        clock=lambda: now[0],
    )
    assert scheduler.acquire("unallocated")
    order: list[str] = []

    def run(stage: str) -> None:
        assert scheduler.acquire(stage, case_id=stage)
        order.append(stage)
        scheduler.release()

    verifier = Thread(target=run, args=("verifier",))
    verifier.start()
    _wait_for_queue(scheduler, 1)
    now[0] = 25.0
    alternative = Thread(target=run, args=("alternative",))
    alternative.start()
    _wait_for_queue(scheduler, 2)
    scheduler.release()
    verifier.join(0.5)
    alternative.join(0.5)

    assert order == ["verifier", "alternative"]


def test_queue_budget_reserves_stage_p95_and_varies_by_stage_and_deadline():
    assert feasible_queue_budget("primary", 500.0, 60.0) == 60.0
    assert feasible_queue_budget("router", 500.0, 60.0) == 40.0
    assert feasible_queue_budget("primary", 132.0, 60.0) == 0.0
    assert feasible_queue_budget("primary", 120.0, 60.0) == 0.0


def test_repair_reverify_requires_one_atomic_time_reserve():
    required = stage_sequence_reserve_seconds(
        ("repair", "verifier"),
        60.0,
    )
    assert required == 450.0
    assert not stage_sequence_feasible(
        ("repair", "verifier"),
        remaining_seconds=required - 0.001,
        maximum_queue_seconds=60.0,
    )
    assert stage_sequence_feasible(
        ("repair", "verifier"),
        remaining_seconds=required,
        maximum_queue_seconds=60.0,
    )


def test_bound_case_and_effective_queue_policy_are_recorded_per_call():
    budget = CallBudget(1)
    session = create_session("1+1", {}, budget)
    budget.consume(stage="primary")
    provider = OfficialClientProvider(
        type("Client", (), {"chat": lambda self, **_: "2"})(),
        ModelCallGate(1),
    )

    assert provider.chat(
        messages=[{"role": "user", "content": "1+1"}],
        temperature=0.0,
        max_tokens=16,
        budget=budget,
        stage="primary",
    ) == "2"

    record = budget.model_call_records[0]
    assert budget.scheduler_case_id == session.session_id
    assert record["stage_p95_seconds"] == 210.0
    assert record["effective_queue_budget_seconds"] == 15.0
    assert budget.to_dict()["scheduler_case_bound"] is True
    assert budget.to_dict()["provider_scheduler_peak"] == 1


def test_healthy_service_forms_all_planned_primary_candidates_at_capacity_four():
    gate = ModelCallGate(4, max_background_tails=4)
    lock = Lock()
    state = {"active": 0, "peak": 0}

    class HealthyClient:
        def chat(self, **_) -> str:
            with lock:
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
            try:
                sleep(0.003)
                return "candidate"
            finally:
                with lock:
                    state["active"] -= 1

    provider = OfficialClientProvider(HealthyClient(), gate)

    def run(index: int) -> str:
        budget = CallBudget(1)
        create_session(f"case {index}", {}, budget)
        budget.consume(stage="primary")
        return provider.chat(
            messages=[{"role": "user", "content": str(index)}],
            temperature=0.0,
            max_tokens=16,
            budget=budget,
            stage="primary",
        )

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(run, range(40)))

    assert results == ["candidate"] * 40
    assert state["peak"] <= 4
    assert gate.health_snapshot()["scheduler"]["peak"] <= 4


def test_capacity_gate_compares_frozen_concurrency_levels():
    profiles = {
        level: {
            "candidate_acceptance_rate": 1.0,
            "success_rate": 0.9,
            "answer_match_rate_on_persisted_cases": 0.8,
            "scheduler": {"peak": level},
        }
        for level in (1, 2, 4)
    }
    result = compare(profiles)
    assert result["passed"] is True
    assert result["comparison"]["answer_production_drop_at_4"] == 0.0
    assert result["observed"]["peak_physical_concurrency"][4] == 4
