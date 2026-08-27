from __future__ import annotations

from threading import Barrier, Lock

import pytest

from mathforge.agent_runtime.definitions import AgentRegistry
from mathforge.agent_runtime.runtime import SessionAgentRuntime
from mathforge.harness.budget import CallBudget
from mathforge.harness.errors import ModelCallRejected
from mathforge.harness.provider import ModelCallGate, OfficialClientProvider
from mathforge.runtime_flows.scheduler_flow import (
    GraphExpansion,
    GraphExecutor,
    NodeOutcome,
    SchedulerTaskBinding,
    TaskGraph,
    TaskNode,
    current_scheduler_task_binding,
    scheduler_task_context,
)
from mathforge.agents.router_planner import RouterPlanner
from mathforge.parsing.problem_parser import ProblemParser


class _RecordingClient:
    def __init__(self, response: str = "ok") -> None:
        self.response = response
        self.calls: list[dict] = []

    def chat(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return self.response


def test_graph_executor_runs_dependency_waves_and_binds_each_operation():
    graph = TaskGraph(
        "e5-waves",
        (
            TaskNode("router", "RouterPlanner", "router", "router"),
            TaskNode(
                "primary",
                "PrimarySolver",
                "solver_progress",
                "primary",
                dependencies=("router",),
                parallel_group="solver-wave",
            ),
            TaskNode(
                "alternative",
                "AlternativeSolver",
                "solver_progress",
                "alternative",
                dependencies=("router",),
                parallel_group="solver-wave",
            ),
            TaskNode(
                "synthesis",
                "PrimarySolver",
                "solver_candidate_standard",
                "synthesis",
                dependencies=("primary", "alternative"),
            ),
        ),
    )
    executor = GraphExecutor(graph, max_workers=2, session_id="e5-session")

    assert [node.node_id for node in executor.ready()] == ["router"]
    assert executor.run_wave(
        ("router",), operations={"router": lambda: "route"}
    )[0].accepted
    assert {node.node_id for node in executor.ready()} == {
        "primary",
        "alternative",
    }

    barrier = Barrier(2)
    lock = Lock()
    bindings: dict[str, tuple[str, str, int]] = {}

    def branch(value: str) -> str:
        binding = current_scheduler_task_binding()
        assert binding is not None
        barrier.wait(timeout=1.0)
        with lock:
            bindings[value] = (
                binding.scheduler_task_id,
                binding.agent_id,
                binding.wave_generation,
            )
        return value

    outcomes = executor.run_wave(
        ("primary", "alternative"),
        operations={
            "primary": lambda: branch("primary"),
            "alternative": lambda: branch("alternative"),
        },
    )
    assert {outcome.value for outcome in outcomes} == {"primary", "alternative"}
    assert bindings["primary"][0] == "primary"
    assert bindings["alternative"][0] == "alternative"
    assert bindings["primary"][2] == bindings["alternative"][2]
    assert all(
        executor.execution(node_id).status == "completed"
        for node_id in ("router", "primary", "alternative")
    )

    synthesis = executor.run_wave(
        ("synthesis",), operations={"synthesis": lambda: "answer"}
    )
    assert synthesis[0].value == "answer"
    assert executor.result().values == {
        "router": "route",
        "primary": "primary",
        "alternative": "alternative",
        "synthesis": "answer",
    }


def test_graph_executor_expansion_and_dependency_violation_are_authoritative():
    graph = TaskGraph(
        "e5-expansion",
        (TaskNode("root", "RouterPlanner", "router", "root"),),
    )
    executor = GraphExecutor(graph, max_workers=1, session_id="e5-session")
    executor.run_wave(("root",), operations={"root": lambda: "root"})

    expansion = GraphExpansion.from_action(
        "request_lemma",
        (
            TaskNode(
                "lemma",
                "LemmaCurator",
                "lemma_curator",
                "lemma",
                operation=lambda: "lemma",
            ),
        ),
        parent_node_id="root",
        plan_version=executor.active_plan_version,
    )
    executor.expand(expansion)
    assert executor.run_wave(("lemma",))[0].value == "lemma"
    assert executor.execution("lemma").status == "completed"

    executor.expand(
        GraphExpansion.from_action(
            "new_branch",
            (
                TaskNode(
                    "pending-parent",
                    "AlternativeSolver",
                    "solver_progress",
                    "pending-parent",
                ),
                TaskNode(
                    "blocked-child",
                    "AlternativeSolver",
                    "solver_candidate_standard",
                    "blocked-child",
                    dependencies=("pending-parent",),
                ),
            ),
            parent_node_id="root",
            plan_version=executor.active_plan_version,
        )
    )
    with pytest.raises(RuntimeError, match="dependency violation"):
        executor.dispatch(("blocked-child",))
    assert executor.snapshot()["dependency_violations"] == ["blocked-child"]


def test_graph_executor_closes_unstarted_nodes_as_terminal_skips():
    graph = TaskGraph(
        "e5-finalize",
        (
            TaskNode("root", "RouterPlanner", "router", "root"),
            TaskNode(
                "optional",
                "VerifierSkeptic",
                "verifier",
                "optional",
                dependencies=("root",),
                optional=True,
            ),
        ),
    )
    executor = GraphExecutor(graph, max_workers=1, session_id="e5-session")
    executor.run_wave(("root",), operations={"root": lambda: "root"})
    assert executor.finalize_pending() == ("optional",)
    assert executor.execution("optional").status == "skipped"
    assert executor.result().skipped == ("optional",)


def test_publish_fence_rejects_result_metadata_mismatch_and_records_late_result():
    graph = TaskGraph(
        "e5-fence",
        (TaskNode("task", "PrimarySolver", "solver_progress", "task"),),
    )
    executor = GraphExecutor(graph, max_workers=1, session_id="e5-session")
    dispatch = executor.dispatch(("task",), operation=lambda: "value")[0]

    forged = NodeOutcome(
        "task",
        value="forged",
        generation=dispatch.generation + 1,
        plan_version=dispatch.plan_version,
        wave_generation=dispatch.wave_generation,
    )
    assert not executor.commit(forged, fence=dispatch.fence)
    assert executor.node_status("task") == "running"
    assert executor.snapshot()["late_results"][-1]["reason"] == "stale_generation"

    valid = NodeOutcome(
        "task",
        value="value",
        generation=dispatch.generation,
        plan_version=dispatch.plan_version,
        wave_generation=dispatch.wave_generation,
    )
    assert executor.commit(valid, fence=dispatch.fence)
    assert executor.result().values == {"task": "value"}


def test_graph_executor_keeps_node_and_scheduler_task_id_boundaries_explicit():
    with pytest.raises(ValueError, match="task identities"):
        TaskGraph(
            "duplicate-task-ids",
            (
                TaskNode("node-a", "PrimarySolver", "solver_progress", "same-task"),
                TaskNode("node-b", "AlternativeSolver", "solver_progress", "same-task"),
            ),
        )

    executor = GraphExecutor(
        TaskGraph(
            "different-identities",
            (TaskNode("node", "PrimarySolver", "solver_progress", "task"),),
        ),
        max_workers=1,
        session_id="e5-session",
    )
    dispatch = executor.dispatch(("node",), operation=lambda: "value")[0]
    assert dispatch.task_id == "task"
    assert dispatch.fence.scheduler_task_id == "task"
    assert executor.commit(
        NodeOutcome(
            "node",
            value="value",
            generation=dispatch.generation,
            plan_version=dispatch.plan_version,
            wave_generation=dispatch.wave_generation,
        ),
        fence=dispatch.fence,
    )


def test_ten_progress_waves_preserve_branch_namespace_and_state_versions():
    graph = TaskGraph(
        "e5-ten-waves",
        (
            TaskNode("root", "RouterPlanner", "router", "root"),
            TaskNode(
                "primary-0",
                "PrimarySolver",
                "solver_progress",
                "primary-0",
                dependencies=("root",),
                parallel_group="solver-wave",
            ),
            TaskNode(
                "alternative-0",
                "AlternativeSolver",
                "solver_progress",
                "alternative-0",
                dependencies=("root",),
                parallel_group="solver-wave",
            ),
        ),
    )
    executor = GraphExecutor(graph, max_workers=2, session_id="e5-session")
    executor.run_wave(("root",), operations={"root": lambda: "route"})
    versions = {"PrimarySolver": [], "AlternativeSolver": []}
    current = {"PrimarySolver": "primary-0", "AlternativeSolver": "alternative-0"}
    for round_index in range(10):
        barrier = Barrier(2)

        def observe(role: str) -> tuple[str, int]:
            binding = current_scheduler_task_binding()
            assert binding is not None
            assert binding.agent_id == role
            barrier.wait(timeout=1.0)
            versions[role].append(round_index)
            return role, round_index

        outcomes = executor.run_wave(
            tuple(current.values()),
            operations={
                current["PrimarySolver"]: lambda: observe("PrimarySolver"),
                current["AlternativeSolver"]: lambda: observe("AlternativeSolver"),
            },
        )
        assert {outcome.value for outcome in outcomes} == {
            ("PrimarySolver", round_index),
            ("AlternativeSolver", round_index),
        }
        if round_index == 9:
            break
        next_nodes = (
            TaskNode(
                f"primary-{round_index + 1}",
                "PrimarySolver",
                "solver_progress",
                f"primary-{round_index + 1}",
                dependencies=(current["PrimarySolver"],),
                parallel_group="solver-wave",
            ),
            TaskNode(
                f"alternative-{round_index + 1}",
                "AlternativeSolver",
                "solver_progress",
                f"alternative-{round_index + 1}",
                dependencies=(current["AlternativeSolver"],),
                parallel_group="solver-wave",
            ),
        )
        executor.expand(
            GraphExpansion.from_action(
                "continue_reasoning",
                next_nodes,
                plan_version=executor.active_plan_version,
            )
        )
        current = {
            "PrimarySolver": next_nodes[0].node_id,
            "AlternativeSolver": next_nodes[1].node_id,
        }
    assert versions["PrimarySolver"] == list(range(10))
    assert versions["AlternativeSolver"] == list(range(10))


def test_replan_version_barrier_cancels_incompatible_work_without_downstream_value():
    graph = TaskGraph(
        "e5-replan",
        (
            TaskNode(
                "old",
                "PrimarySolver",
                "solver_progress",
                "old",
                plan_version=1,
            ),
            TaskNode(
                "downstream",
                "PrimarySolver",
                "solver_candidate_standard",
                "downstream",
                dependencies=("old",),
                plan_version=1,
            ),
        ),
    )
    executor = GraphExecutor(
        graph,
        max_workers=1,
        session_id="e5-session",
        plan_version=1,
    )
    dispatch = executor.dispatch(("old",), operation=lambda: "late")[0]
    assert executor.cancel_plan_version(2) == ("old", "downstream")
    late = NodeOutcome(
        "old",
        value="late",
        generation=dispatch.generation,
        plan_version=1,
        wave_generation=dispatch.wave_generation,
    )
    assert not executor.commit(late, fence=dispatch.fence)
    result = executor.result()
    assert result.values == {}
    assert result.skipped == ("downstream", "old")
    assert result.late_results[-1]["reason"] == "stale_plan_version"


def test_scheduler_flow_default_binding_and_strict_provider_gate():
    seen: list[str] = []
    from mathforge.runtime_flows.scheduler_flow import SchedulerFlow

    scheduler = SchedulerFlow(max_workers=1)
    scheduler.run_parallel(
        (("legacy-task", lambda: seen.append(
            current_scheduler_task_binding().scheduler_task_id
        ) or "ok"),),
        generation_scope="legacy-graph",
    )
    assert seen == ["legacy-task"]

    client = _RecordingClient()
    provider = OfficialClientProvider(client, ModelCallGate(1))
    budget = CallBudget(
        1,
        require_scheduler_binding=True,
        model_call_start_margin_seconds=0.0,
    )
    with pytest.raises(ModelCallRejected) as rejected:
        provider.chat(
            messages=[{"role": "user", "content": "x"}],
            temperature=0.0,
            max_tokens=16,
            budget=budget,
            stage="solver_progress",
            agent_id="PrimarySolver",
        )
    assert rejected.value.code == "scheduler_task_unbound"

    budget.consume(stage="solver_progress")
    with scheduler_task_context(
        SchedulerTaskBinding(
            scheduler_task_id="bound-task",
            plan_version=3,
            agent_id="PrimarySolver",
            turn_id="",
            graph_id="bound-graph",
        )
    ):
        assert provider.chat(
            messages=[{"role": "user", "content": "x"}],
            temperature=0.0,
            max_tokens=16,
            budget=budget,
            stage="solver_progress",
            agent_id="PrimarySolver",
        ) == "ok"
    record = budget.model_call_records[0]
    assert record["scheduler_task_id"] == "bound-task"
    assert record["scheduler_agent_id"] == "PrimarySolver"
    assert record["scheduler_plan_version"] == 3
    assert record["scheduler_binding_status"] == "bound"

    strict_budget = CallBudget(
        1,
        require_scheduler_binding=True,
        model_call_start_margin_seconds=0.0,
    )
    strict_outcome = scheduler.run_parallel(
        ((
            "legacy-strict",
            lambda: provider.chat(
                messages=[{"role": "user", "content": "x"}],
                temperature=0.0,
                max_tokens=16,
                budget=strict_budget,
                stage="solver_progress",
                agent_id="PrimarySolver",
            ),
        ),),
        generation_scope="legacy-strict-graph",
    )[0]
    assert isinstance(strict_outcome.error, ModelCallRejected)
    assert strict_outcome.error.code == "scheduler_task_unbound"


def test_critical_path_admission_includes_reserves_strictly():
    from mathforge.runtime_flows.scheduler_flow import SchedulerFlow

    graph = TaskGraph(
        "e5-admission",
        (TaskNode("task", "PrimarySolver", "solver_progress", "task", expected_p95=10),),
    )
    scheduler = SchedulerFlow(max_workers=1)
    assert scheduler.critical_path_admitted(
        graph,
        remaining_seconds=10.2,
        finalize_reserve_seconds=0.05,
        model_start_margin_seconds=0.05,
    )
    assert not scheduler.critical_path_admitted(
        graph,
        remaining_seconds=10.1,
        finalize_reserve_seconds=0.1,
        model_start_margin_seconds=0.0,
    )


def test_replan_ack_is_recorded_only_from_real_solver_turns():
    runtime = SessionAgentRuntime("e" * 32, AgentRegistry.default())
    problem = ProblemParser().parse("Prove that x^2 is nonnegative for every real x.")
    first = RouterPlanner().plan_authoritative(problem)
    second = RouterPlanner().plan_authoritative(
        problem,
        previous_plan=first.authoritative_plan,
    )
    runtime.publish_router_decision(
        route_payload=first.route_plan.to_dict(),
        plan=first.authoritative_plan,
    )
    runtime.publish_router_decision(
        route_payload=second.route_plan.to_dict(),
        plan=second.authoritative_plan,
    )
    barrier = runtime.replan_barrier
    assert barrier is not None and barrier["status"] == "paused"

    contexts = []
    for descriptor in ("primary-1", "alternative-1", "alternative-2"):
        role = "PrimarySolver" if descriptor.startswith("primary") else "AlternativeSolver"
        contexts.append(
            runtime.begin_model_turn(
                stage="primary" if role == "PrimarySolver" else "alternative",
                turn_kind="solver_progress",
                agent_hint=f"{role}:{descriptor}",
                allow_replan_ack=True,
            )
        )
    for context in contexts:
        assert runtime.replan_ack_required(context.turn_id)
        runtime.acknowledge_replan_from_turn(
            context.turn_id,
            second.authoritative_plan.version,
            "apply",
        )
    assert runtime.resume_replan_if_ready()
    assert runtime.replan_barrier["status"] == "resumed"
    events = [
        event
        for event in runtime._protocol_events
        if event["event_type"] == "replan_acknowledged"
    ]
    assert len(events) == len(contexts)
    assert all(event["source"] == "agent_turn" for event in events)
