from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import gc
import json
from threading import Event, Lock, Thread
from time import perf_counter, sleep
import weakref

import pytest

from mathforge.config import HarnessConfig, load_competition_config
from mathforge.harness.budget import CallBudget
from mathforge.harness.deadline import DeadlineController
from mathforge.harness.errors import ModelCallRejected
from mathforge.harness.priority_scheduler import PriorityCallScheduler
from mathforge.harness.provider import ModelCallGate, OfficialClientProvider
from mathforge.harness.session import create_session
from mathforge.harness.trace import TraceBuilder
from mathforge.runtime import MathForgeHarness
from tests.fake_client import FakeClient


def _deadline(seconds: float = 0.25) -> DeadlineController:
    return DeadlineController(
        soft_deadline_seconds=seconds,
        exploration_deadline_seconds=seconds,
        hard_deadline_seconds=seconds,
        deterministic_finalize_reserve_seconds=min(0.005, seconds / 10),
        model_call_start_margin_seconds=0.0,
    )


def _minimal_config(**overrides) -> HarnessConfig:
    values = {
        "profile": "phase2-test",
        "status": "test",
        "max_model_calls": 1,
        "model_max_concurrency": 2,
        "max_background_model_tails": 2,
        "enable_router": False,
        "enable_skills": False,
        "enable_alternatives": False,
        "enable_tools": False,
        "enable_evidence": False,
        "enable_proof_obligations": False,
        "enable_verifier": False,
        "enable_memory": False,
        "enable_lemma_loop": False,
        "enable_rag": False,
        "enable_repair": False,
        "enable_finalizer": False,
    }
    values.update(overrides)
    return HarnessConfig(**values)


def test_queue_budget_fails_fast_records_wait_and_reuses_released_slot():
    entered = Event()
    release = Event()
    gate = ModelCallGate(1, max_background_tails=1)

    def occupying_call() -> str:
        entered.set()
        release.wait(1)
        return "first"

    first_result: list[str] = []
    first = Thread(
        target=lambda: first_result.append(
            gate.call(
                occupying_call,
                deadline=_deadline(0.5),
                queue_budget_seconds=0.2,
                stage_timeout_seconds=0.4,
            )
        )
    )
    first.start()
    assert entered.wait(0.2)

    budget = CallBudget(
        1,
        model_queue_budget_seconds=0.02,
        soft_deadline_seconds=0.5,
        exploration_deadline_seconds=0.5,
        hard_deadline_seconds=0.5,
        deterministic_finalize_reserve_seconds=0.01,
        model_call_start_margin_seconds=0.0,
    )
    budget.consume(stage="primary")
    provider = OfficialClientProvider(
        type("Client", (), {"chat": lambda self, **_: "second"})(),
        gate,
    )
    started = perf_counter()
    with pytest.raises(ModelCallRejected) as captured:
        provider.chat(
            messages=[{"role": "user", "content": "queued"}],
            temperature=0.0,
            max_tokens=16,
            budget=budget,
            stage="primary",
        )
    elapsed = perf_counter() - started

    assert captured.value.code == "model_concurrency_wait_exceeded"
    assert elapsed < 0.15
    record = budget.model_call_records[0]
    assert record["dispatched"] is False
    assert record["failure_code"] == "model_concurrency_wait_exceeded"
    assert 0.0 < record["queue_elapsed_seconds"] < 0.15
    assert record["execution_elapsed_seconds"] == 0.0
    assert budget.model_queue_timeout_count == 1
    assert budget.used_calls == 0

    release.set()
    first.join(0.5)
    assert first_result == ["first"]
    assert (
        gate.call(
            lambda: "reused",
            deadline=_deadline(),
            queue_budget_seconds=0.05,
            stage_timeout_seconds=0.1,
        )
        == "reused"
    )


def test_stage_timeout_includes_queue_wait_instead_of_extending_after_admission():
    entered = Event()
    release = Event()
    gate = ModelCallGate(1, max_background_tails=1)
    holder = Thread(
        target=lambda: gate.call(
            lambda: (entered.set(), release.wait(1), "held")[-1],
            deadline=_deadline(0.5),
            queue_budget_seconds=0.2,
            stage_timeout_seconds=0.4,
        )
    )
    holder.start()
    assert entered.wait(0.2)

    def release_later() -> None:
        sleep(0.035)
        release.set()

    Thread(target=release_later).start()
    timings: list[dict[str, float]] = []
    started = perf_counter()
    with pytest.raises(ModelCallRejected) as captured:
        gate.call(
            lambda: (sleep(0.08), "late")[1],
            deadline=_deadline(0.5),
            queue_budget_seconds=0.1,
            stage_timeout_seconds=0.06,
            timing_callback=timings.append,
        )
    elapsed = perf_counter() - started
    holder.join(0.5)

    assert captured.value.code == "model_response_deadline_exceeded"
    assert 0.045 <= elapsed < 0.13
    assert timings[0]["queue_elapsed_seconds"] >= 0.02
    assert timings[0]["execution_elapsed_seconds"] < 0.06
    assert timings[0]["total_elapsed_seconds"] < 0.13


def test_timed_out_tail_opens_circuit_fast_fails_and_resets_after_completion():
    entered = Event()
    release = Event()

    class BlockingClient:
        def chat(self, **_) -> str:
            entered.set()
            release.wait(1)
            return "late response"

    gate = ModelCallGate(1, max_background_tails=1)
    provider = OfficialClientProvider(BlockingClient(), gate)
    first_budget = CallBudget(
        1,
        model_queue_budget_seconds=0.02,
        soft_deadline_seconds=0.04,
        exploration_deadline_seconds=0.04,
        hard_deadline_seconds=0.04,
        deterministic_finalize_reserve_seconds=0.005,
        model_call_start_margin_seconds=0.0,
    )
    with pytest.raises(ModelCallRejected) as captured:
        provider.chat(
            messages=[{"role": "user", "content": "block"}],
            temperature=0.0,
            max_tokens=16,
            budget=first_budget,
            stage="primary",
        )
    assert captured.value.code == "model_response_deadline_exceeded"
    assert entered.is_set()
    assert gate.health_snapshot()["state"] == "circuit_open"
    assert gate.health_snapshot()["active_tails"] == 1

    second_budget = CallBudget(1, model_queue_budget_seconds=0.2)
    started = perf_counter()
    with pytest.raises(ModelCallRejected) as captured:
        provider.chat(
            messages=[{"role": "user", "content": "fast fail"}],
            temperature=0.0,
            max_tokens=16,
            budget=second_budget,
            stage="primary",
        )
    assert perf_counter() - started < 0.05
    assert captured.value.code == "model_provider_circuit_open"
    assert second_budget.model_admission_rejection_count == 1

    release.set()
    for _ in range(100):
        if gate.health_snapshot()["active_tails"] == 0:
            break
        sleep(0.002)
    snapshot = gate.health_snapshot()
    assert snapshot["state"] == "healthy"
    assert snapshot["active_tails"] == 0
    assert snapshot["peak_tails"] == 1
    assert snapshot["circuit_trips"] == 1
    assert snapshot["late_registry"][-1] == {
        "call_index": 1,
        "completion_status": "completed",
        "elapsed_seconds": snapshot["late_registry"][-1]["elapsed_seconds"],
    }


def test_one_timed_out_tail_retains_physical_capacity_until_it_finishes():
    release = Event()
    gate = ModelCallGate(1, max_background_tails=3)

    with pytest.raises(ModelCallRejected) as captured:
        gate.call(
            lambda: (release.wait(1), "late")[1],
            deadline=_deadline(0.03),
            queue_budget_seconds=0.01,
            stage_timeout_seconds=0.02,
        )

    assert captured.value.code == "model_response_deadline_exceeded"
    assert captured.value.dispatched is True
    assert gate.health_snapshot()["state"] == "degraded"
    with pytest.raises(ModelCallRejected) as queued:
        gate.call(
            lambda: "next",
            deadline=_deadline(0.2),
            queue_budget_seconds=0.02,
            stage_timeout_seconds=0.02,
        )
    assert queued.value.code == "model_concurrency_wait_exceeded"
    assert queued.value.dispatched is False
    assert gate.health_snapshot()["scheduler"]["active"] == 1
    release.set()
    for _ in range(100):
        if gate.health_snapshot()["scheduler"]["active"] == 0:
            break
        sleep(0.002)
    assert (
        gate.call(
            lambda: "after-tail",
            deadline=_deadline(0.2),
            queue_budget_seconds=0.05,
            stage_timeout_seconds=0.1,
        )
        == "after-tail"
    )


def test_priority_scheduler_admits_primary_before_earlier_alternative():
    scheduler = PriorityCallScheduler(1)
    assert scheduler.acquire("unallocated")
    admission_order: list[str] = []

    def wait_for(stage: str) -> None:
        assert scheduler.acquire(stage, 0.5)
        admission_order.append(stage)
        scheduler.release()

    alternative = Thread(target=wait_for, args=("alternative",))
    primary = Thread(target=wait_for, args=("primary",))
    alternative.start()
    for _ in range(100):
        if scheduler.snapshot()["queued"] == 1:
            break
        sleep(0.001)
    primary.start()
    for _ in range(100):
        if scheduler.snapshot()["queued"] == 2:
            break
        sleep(0.001)
    scheduler.release()
    alternative.join(0.5)
    primary.join(0.5)

    assert admission_order == ["primary", "alternative"]
    assert scheduler.snapshot()["peak"] == 1


def test_eight_requests_never_exceed_four_physical_model_calls():
    gate = ModelCallGate(4, max_background_tails=4)
    release = Event()
    lock = Lock()
    state = {"active": 0, "peak": 0}

    def call() -> str:
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        try:
            release.wait(1)
            return "ok"
        finally:
            with lock:
                state["active"] -= 1

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(gate.call, call, stage="primary") for _ in range(8)]
        for _ in range(200):
            if gate.health_snapshot()["scheduler"]["active"] == 4:
                break
            sleep(0.001)
        assert gate.health_snapshot()["scheduler"]["active"] == 4
        release.set()
        assert [future.result() for future in futures] == ["ok"] * 8

    assert state["peak"] == 4
    assert gate.health_snapshot()["scheduler"]["peak"] == 4


def test_one_hung_tail_keeps_one_hundred_followup_requests_thread_bounded():
    release = Event()
    gate = ModelCallGate(1, max_background_tails=1)
    with pytest.raises(ModelCallRejected):
        gate.call(
            lambda: (release.wait(1), "late")[1],
            deadline=_deadline(0.03),
            queue_budget_seconds=0.01,
            stage_timeout_seconds=0.02,
        )

    for _ in range(100):
        with pytest.raises(ModelCallRejected) as captured:
            gate.call(
                lambda: "must not start",
                deadline=_deadline(),
                queue_budget_seconds=0.1,
                stage_timeout_seconds=0.1,
            )
        assert captured.value.code == "model_provider_circuit_open"

    snapshot = gate.health_snapshot()
    assert snapshot["active_tails"] == 1
    assert snapshot["peak_tails"] == 1
    assert snapshot["fast_failures"] == 100
    release.set()


def test_late_tail_does_not_retain_or_mutate_a_frozen_session():
    release = Event()

    class BlockingClient:
        def chat(self, **_) -> str:
            release.wait(1)
            return "late"

    gate = ModelCallGate(1, max_background_tails=1)
    provider = OfficialClientProvider(BlockingClient(), gate)
    budget = CallBudget(
        1,
        model_queue_budget_seconds=0.01,
        soft_deadline_seconds=0.03,
        exploration_deadline_seconds=0.03,
        hard_deadline_seconds=0.03,
        deterministic_finalize_reserve_seconds=0.005,
        model_call_start_margin_seconds=0.0,
    )
    session = create_session("problem-private", {}, budget)
    with pytest.raises(ModelCallRejected):
        provider.chat(
            messages=[{"role": "user", "content": session.problem}],
            temperature=0.0,
            max_tokens=16,
            budget=session.budget,
            stage="primary",
        )
    session.freeze()
    session_ref = weakref.ref(session)
    budget_snapshot = json.dumps(session.budget.to_dict(), sort_keys=True)
    del session
    del budget
    gc.collect()

    assert session_ref() is None
    release.set()
    for _ in range(100):
        if gate.health_snapshot()["active_tails"] == 0:
            break
        sleep(0.002)
    assert budget_snapshot


def test_session_and_trace_reject_mutation_after_terminal_freeze():
    session = create_session("1+1", {}, CallBudget(1))
    trace = TraceBuilder(session.trace_events)
    trace.add("session_started", session_id=session.session_id)
    session.freeze()
    trace.freeze()

    assert session.is_frozen
    with pytest.raises(RuntimeError, match="frozen"):
        session.transition(session.phase, session.phase, reason="late")
    with pytest.raises(RuntimeError, match="frozen"):
        trace.add("run_completed", outcome="fallback")


@pytest.mark.parametrize("workers", [2, 4, 8])
def test_shared_harness_concurrency_is_isolated_bounded_and_serializable(workers):
    client = FakeClient(delay=0.002)
    harness = MathForgeHarness(client, _minimal_config())

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(
            pool.map(
                lambda index: harness.solve(f"Compute {index}+1.", {"idx": index}),
                range(workers),
            )
        )

    assert client.max_active_calls <= 2
    assert len({result["run_metrics"]["session_id"] for result in results}) == workers
    assert all(json.loads(json.dumps(result)) == result for result in results)


def test_competition_deadline_profile_is_explicit_and_preserves_terminal_reserves():
    config = load_competition_config()
    assert config.outer_platform_limit_seconds == 900.0
    assert config.hard_deadline_seconds == 850.0
    assert config.soft_deadline_seconds == 600.0
    assert config.exploration_deadline_seconds == 720.0
    assert config.deterministic_finalize_reserve_seconds == 50.0
    assert config.model_queue_budget_seconds > 0
    assert config.model_max_concurrency == 16
    assert config.max_background_model_tails == 16
    assert config.hard_deadline_seconds < config.outer_platform_limit_seconds

    now = [0.0]
    deadline = DeadlineController(
        soft_deadline_seconds=600.0,
        exploration_deadline_seconds=720.0,
        hard_deadline_seconds=850.0,
        deterministic_finalize_reserve_seconds=50.0,
        model_call_start_margin_seconds=100.0,
        clock=lambda: now[0],
    )
    now[0] = 800.0
    assert deadline.must_finalize()
    assert deadline.can_start_stage()
    assert not deadline.can_start_model_call()
    now[0] = 850.0
    assert deadline.hard_expired()
