from __future__ import annotations

from threading import Barrier, Lock

import pytest

from mathforge.agent_runtime.call_ledger import CallLedger
from mathforge.config import load_competition_config
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

    assert config.case_max_concurrency == 3
    assert config.model_max_concurrency <= 6
    assert config.model_requests_per_minute <= 200
    assert config.max_inflight_calls_per_agent == 1
