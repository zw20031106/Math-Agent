from __future__ import annotations

from threading import Barrier, Event, Lock
from time import perf_counter, sleep

import pytest

from mathforge.agent_runtime.call_ledger import CallLedger
from mathforge.config import load_competition_config
from mathforge.harness.cancellation import CancellationToken
from mathforge.harness.deadline import DeadlineController
from mathforge.harness.provider import ModelCallGate
from mathforge.runtime_flows.scheduler_flow import SchedulerFlow, TaskGraph, TaskNode


def test_task_graph_critical_path_counts_parallel_waves_once():
    graph = TaskGraph(
        "case-graph",
        (
            TaskNode("router", "RouterPlanner", "router", "t-router", expected_p95=10),
            TaskNode(
                "primary",
                "PrimarySolver",
                "candidate_completion",
                "t-primary",
                dependencies=("router",),
                expected_p95=100,
                parallel_group="solver-wave",
            ),
            TaskNode(
                "alternative",
                "AlternativeSolver",
                "candidate_completion",
                "t-alternative",
                dependencies=("router",),
                expected_p95=80,
                parallel_group="solver-wave",
            ),
            TaskNode(
                "review-primary",
                "AlternativeSolver",
                "peer_review",
                "t-review-primary",
                dependencies=("primary", "alternative"),
                expected_p95=40,
                parallel_group="review-wave",
            ),
            TaskNode(
                "review-alternative",
                "PrimarySolver",
                "peer_review",
                "t-review-alternative",
                dependencies=("primary", "alternative"),
                expected_p95=40,
                parallel_group="review-wave",
            ),
            TaskNode(
                "verify",
                "VerifierSkeptic",
                "verifier",
                "t-verify",
                dependencies=("review-primary", "review-alternative"),
                expected_p95=50,
            ),
        ),
    )

    assert graph.critical_path_p95 == 200
    assert {node.node_id for node in graph.ready_nodes({"router"})} == {
        "primary",
        "alternative",
    }
    assert graph.to_dict()["critical_path_p95_seconds"] == 200


def test_task_graph_rejects_cycles_and_unknown_dependencies():
    with pytest.raises(ValueError, match="unknown"):
        TaskGraph(
            "unknown",
            (TaskNode("a", "Host", "work", "t-a", dependencies=("missing",)),),
        )
    with pytest.raises(ValueError, match="acyclic"):
        TaskGraph(
            "cycle",
            (
                TaskNode("a", "Host", "work", "t-a", dependencies=("b",)),
                TaskNode("b", "Host", "work", "t-b", dependencies=("a",)),
            ),
        )


def test_atomic_closure_admission_rejects_speculation_and_partial_capacity():
    scheduler = SchedulerFlow(max_workers=2)
    repair = TaskNode("repair", "RepairAgent", "repair", "repair", closure_value=1)
    verify = TaskNode(
        "verify",
        "VerifierSkeptic",
        "verifier",
        "verify",
        dependencies=("repair",),
        closure_value=1,
    )
    speculative = TaskNode(
        "explore",
        "AlternativeSolver",
        "solver_progress",
        "explore",
        optional=True,
    )

    rejected = scheduler.admit_closure(
        (repair, speculative),
        remaining_calls=10,
        remaining_seconds=1000,
        maximum_queue_seconds=15,
    )
    partial = scheduler.admit_closure(
        (repair, verify),
        remaining_calls=1,
        remaining_seconds=1000,
        maximum_queue_seconds=15,
    )
    admitted = scheduler.admit_closure(
        (repair, verify),
        remaining_calls=2,
        remaining_seconds=1000,
        maximum_queue_seconds=15,
    )

    assert rejected.reason == "speculative_action_in_closure"
    assert partial.reason == "insufficient_call_capacity"
    assert admitted.admitted
    assert admitted.required_calls == 2
    assert admitted.node_ids == ("repair", "verify")


def test_parallel_wave_overlaps_independent_tasks_and_bounds_workers():
    scheduler = SchedulerFlow(max_workers=2)
    barrier = Barrier(2)
    lock = Lock()
    active = 0
    peak = 0

    def work(value: int) -> int:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        barrier.wait(timeout=1)
        with lock:
            active -= 1
        return value

    outcomes = scheduler.run_parallel(
        (("primary", lambda: work(1)), ("alternative", lambda: work(2)))
    )

    assert peak == 2
    assert [outcome.value for outcome in outcomes] == [1, 2]
    assert all(outcome.error is None for outcome in outcomes)


def test_call_ledger_accounts_every_record_by_role_action_and_task():
    ledger = CallLedger()
    first = ledger.start(
        {
            "agent_role": "PrimarySolver",
            "action_category": "candidate_completion",
            "task_id": "solve-primary",
            "status": "started",
        }
    )
    ledger.update(first, {"status": "completed", "dispatched": True})
    ledger.start(
        {
            "agent_role": "VerifierSkeptic",
            "action_category": "verification",
            "task_id": "verify-primary",
            "status": "failed",
            "dispatched": True,
        }
    )

    accounting = ledger.accounting_snapshot()

    assert accounting["recorded_calls"] == 2
    assert accounting["dispatched_calls"] == 2
    assert accounting["by_role"] == {"PrimarySolver": 1, "VerifierSkeptic": 1}
    assert accounting["by_action"] == {
        "candidate_completion": 1,
        "verification": 1,
    }
    assert accounting["by_task"] == {
        "solve-primary": 1,
        "verify-primary": 1,
    }


def test_competition_resource_boundaries_remain_frozen_for_phase9():
    config = load_competition_config()

    assert config.case_max_concurrency == 2
    assert config.model_max_concurrency == 6
    assert config.model_requests_per_minute == 200
    assert config.max_inflight_calls_per_agent == 1
    assert config.transport_attempt_reservation == 3
    assert config.max_background_model_tails == 2
    assert config.provider_tail_grace_seconds == pytest.approx(0.1)
    assert config.stage_execution_policy["solver_candidate_standard"][
        "max_tokens"
    ] == 32768
    assert config.stage_execution_policy["solver_candidate_proof"][
        "max_tokens"
    ] == 40960


def test_provider_timeout_is_a_stage_boundary_with_isolated_short_tail():
    release = Event()
    gate = ModelCallGate(
        2,
        max_background_tails=2,
        tail_grace_seconds=0.01,
    )
    deadline = DeadlineController(
        soft_deadline_seconds=1.0,
        exploration_deadline_seconds=1.0,
        hard_deadline_seconds=1.0,
        deterministic_finalize_reserve_seconds=0.01,
        model_call_start_margin_seconds=0.0,
    )

    started = perf_counter()
    with pytest.raises(Exception) as captured:
        gate.call(
            lambda: (release.wait(1.0), "late")[1],
            case_id="case-a",
            deadline=deadline,
            stage_timeout_seconds=0.02,
        )
    elapsed = perf_counter() - started

    assert captured.value.code == "model_response_deadline_exceeded"
    assert elapsed < 0.12
    assert gate.health_snapshot("case-a")["active_tails"] == 1
    # A late tail from case-a must not open or populate case-b's registry.
    assert gate.call(lambda: "ok", case_id="case-b") == "ok"
    assert gate.health_snapshot("case-b")["late_registry"] == []

    release.set()
    for _ in range(100):
        if gate.health_snapshot("case-a")["active_tails"] == 0:
            break
        sleep(0.002)
    assert gate.health_snapshot("case-a")["late_registry"][-1][
        "completion_status"
    ] == "completed"


def test_wave_timeout_cancels_and_fences_pending_generation():
    release = Event()
    token = CancellationToken()
    scheduler = SchedulerFlow(max_workers=2)

    outcomes = scheduler.run_parallel(
        (
            ("slow", lambda: (release.wait(1.0), "late")[1]),
            ("fast", lambda: (sleep(0.2), "late-fast")[1]),
        ),
        timeout_seconds=0.02,
        generation_scope="phase9-fence",
        cancellation_token=token,
    )

    assert token.is_cancelled
    assert token.reason == "scheduler_wave_timeout"
    assert all(not outcome.accepted for outcome in outcomes)
    assert not scheduler.accepts_generation(
        "slow",
        next(outcome for outcome in outcomes if outcome.task_id == "slow").generation,
        scope="phase9-fence",
    )

    release.set()
    sleep(0.03)
