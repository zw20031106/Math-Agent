from __future__ import annotations

from mathforge.runtime_flows.scheduler_flow import (
    SchedulerFlow,
    TaskGraph,
    TaskNode,
)


def test_task_graph_binds_operations_and_returns_dependency_waves():
    graph = TaskGraph(
        "graph-bind",
        (
            TaskNode("router", "RouterPlanner", "router", "router"),
            TaskNode(
                "primary",
                "PrimarySolver",
                "candidate_completion",
                "primary",
                dependencies=("router",),
                parallel_group="solver-wave",
            ),
            TaskNode(
                "alternative",
                "AlternativeSolver",
                "candidate_completion",
                "alternative",
                dependencies=("router",),
                parallel_group="solver-wave",
            ),
        ),
    ).bind_operations(
        {"router": lambda: "route", "primary": lambda: 1, "alternative": lambda: 2}
    )

    assert [[node.node_id for node in wave] for wave in graph.ready_waves(set())] == [
        ["router"]
    ]
    assert {node.node_id for node in graph.ready_wave({"router"})} == {
        "primary",
        "alternative",
    }
    assert graph.node("router").operation() == "route"


def test_scheduler_graph_executes_waves_and_prunes_optional_nodes():
    graph = TaskGraph(
        "graph-run",
        (
            TaskNode("router", "RouterPlanner", "router", "router"),
            TaskNode(
                "solver",
                "PrimarySolver",
                "candidate_completion",
                "solver",
                dependencies=("router",),
            ),
            TaskNode(
                "review",
                "VerifierSkeptic",
                "verification",
                "review",
                dependencies=("solver",),
                optional=True,
            ),
            TaskNode(
                "final",
                "DeterministicHost",
                "finalization",
                "final",
                dependencies=("review",),
            ),
        ),
    ).bind_operations(
        {
            "router": lambda: "route",
            "solver": lambda: "candidate",
            "review": lambda: "verified",
            "final": lambda: "answer",
        }
    )
    scheduler = SchedulerFlow(max_workers=2)
    pruned, removed = scheduler.prune_infeasible_optional(
        graph,
        remaining_calls=3,
        remaining_seconds=0.1,
    )
    assert removed == ("review",)
    result = scheduler.run_graph(pruned)
    assert result.values == {"router": "route", "solver": "candidate", "final": "answer"}
    assert result.failed == ()
    assert result.skipped == ()
    assert [node.status for node in result.nodes] == [
        "completed",
        "completed",
        "completed",
    ]


def test_generation_token_rejects_a_late_result():
    scheduler = SchedulerFlow(max_workers=1)
    first = scheduler.issue_generation("solver", scope="case")
    second = scheduler.issue_generation("solver", scope="case")

    assert second > first
    assert not scheduler.accepts_generation("solver", first, scope="case")
    assert scheduler.accepts_generation("solver", second, scope="case")


def test_parallel_p95_respects_actual_worker_count():
    graph = TaskGraph(
        "graph-p95",
        tuple(
            TaskNode(
                f"solver-{index}",
                "PrimarySolver",
                "candidate_completion",
                f"solver-{index}",
                expected_p95=10,
                parallel_group="solver-wave",
            )
            for index in range(3)
        ),
    )

    assert graph.critical_path_p95_for_workers(3) == 10
    assert graph.critical_path_p95_for_workers(2) == 20
