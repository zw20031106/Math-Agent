from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from time import perf_counter, sleep

from mathforge.harness.provider import ModelCallGate
from mathforge.harness.rate_limit import WeightedRollingRateLimiter
from mathforge.harness.deadline import DeadlineController
from mathforge.harness.errors import ModelCallRejected


def test_weighted_rate_reservations_refund_only_before_commit():
    limiter = WeightedRollingRateLimiter(5, 60.0)
    first = limiter.try_reserve(3)
    assert first is not None
    assert limiter.try_reserve(3) is None
    assert limiter.refund(first) is True

    committed = limiter.try_reserve(3)
    assert committed is not None
    limiter.commit(committed)
    assert limiter.refund(committed) is False
    snapshot = limiter.snapshot()
    assert snapshot["reserved_weight"] == 3
    assert snapshot["peak_weight"] <= 5


def test_gate_enforces_weighted_rolling_request_limit():
    gate = ModelCallGate(
        3,
        requests_per_minute=2,
        rate_limit_window_seconds=0.06,
        transport_attempt_reservation=1,
    )
    assert gate.call(lambda: "one") == "one"
    assert gate.call(lambda: "two") == "two"

    started = perf_counter()
    assert gate.call(lambda: "three") == "three"
    assert perf_counter() - started >= 0.04
    rate = gate.health_snapshot()["rate_limit"]
    assert rate["limit"] == 2
    assert rate["peak_weight"] <= 2
    assert rate["wait_count"] >= 1


def test_weight_three_allows_66_and_weight_one_allows_200_reservations():
    weighted = WeightedRollingRateLimiter(200, 60.0)
    assert all(weighted.try_reserve(3) is not None for _ in range(66))
    assert weighted.try_reserve(3) is None

    physical = WeightedRollingRateLimiter(200, 60.0)
    assert all(physical.try_reserve(1) is not None for _ in range(200))
    assert physical.try_reserve(1) is None


def test_same_agent_has_one_inflight_call_while_distinct_agents_can_overlap():
    gate = ModelCallGate(
        2,
        requests_per_minute=200,
        transport_attempt_reservation=1,
    )
    release = Event()
    first_started = Event()
    second_started = Event()
    lock = Lock()
    active = 0
    peak = 0

    def call(started: Event) -> str:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        started.set()
        try:
            release.wait(1.0)
            return "ok"
        finally:
            with lock:
                active -= 1

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            gate.call,
            lambda: call(first_started),
            case_id="case-a",
            agent_id="PrimarySolver",
        )
        assert first_started.wait(0.2)
        second = pool.submit(
            gate.call,
            lambda: call(second_started),
            case_id="case-a",
            agent_id="PrimarySolver",
        )
        sleep(0.03)
        assert not second_started.is_set()
        release.set()
        assert first.result() == second.result() == "ok"
    assert peak == 1

    release.clear()
    first_started.clear()
    second_started.clear()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            gate.call,
            lambda: call(first_started),
            case_id="case-b",
            agent_id="PrimarySolver",
        )
        second = pool.submit(
            gate.call,
            lambda: call(second_started),
            case_id="case-b",
            agent_id="VerifierSkeptic",
        )
        assert first_started.wait(0.2)
        assert second_started.wait(0.2)
        release.set()
        assert first.result() == second.result() == "ok"
    assert peak == 2


def test_background_tail_retains_the_same_agent_inflight_slot():
    gate = ModelCallGate(
        2,
        requests_per_minute=200,
        transport_attempt_reservation=1,
        max_background_tails=2,
    )
    release = Event()
    entered = Event()
    calls = 0
    lock = Lock()

    def hung() -> str:
        nonlocal calls
        with lock:
            calls += 1
        entered.set()
        release.wait(1.0)
        return "late"

    deadline = DeadlineController(
        soft_deadline_seconds=0.5,
        exploration_deadline_seconds=0.5,
        hard_deadline_seconds=0.5,
        deterministic_finalize_reserve_seconds=0.01,
        model_call_start_margin_seconds=0.0,
    )
    try:
        try:
            gate.call(
                hung,
                deadline=deadline,
                queue_budget_seconds=0.02,
                stage_timeout_seconds=0.03,
                case_id="case-tail",
                agent_id="PrimarySolver",
            )
        except ModelCallRejected as error:
            assert error.code == "model_response_deadline_exceeded"
        assert entered.is_set()

        try:
            gate.call(
                lambda: "must-not-dispatch",
                deadline=deadline,
                queue_budget_seconds=0.02,
                stage_timeout_seconds=0.1,
                case_id="case-tail",
                agent_id="PrimarySolver",
            )
        except ModelCallRejected as error:
            assert error.code == "model_agent_inflight_wait_exceeded"
        assert calls == 1
    finally:
        release.set()
    for _ in range(100):
        if gate.health_snapshot()["active_tails"] == 0:
            break
        sleep(0.005)
    assert gate.health_snapshot()["active_tails"] == 0
