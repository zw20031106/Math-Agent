from __future__ import annotations

import json

import pytest

from mathforge.agent_runtime.action_registry import ActionRegistry
from mathforge.agent_runtime.artifact_store import stable_payload_hash
from mathforge.agent_runtime.definitions import AgentRegistry
from mathforge.agent_runtime.permissions import permission_for
from mathforge.agent_runtime.protocol import AgentTurnPayload, TurnContext
from mathforge.agent_runtime.runtime import SessionAgentRuntime
from mathforge.agents.registry import PromptContractLoader
from mathforge.agents.router_planner import RouterPlanner
from mathforge.parsing.problem_parser import ProblemParser


def _plans():
    problem = ProblemParser().parse(
        "Prove that x^2 is nonnegative for every real x."
    )
    first = RouterPlanner().plan_authoritative(problem)
    second = RouterPlanner().plan_authoritative(
        problem,
        previous_plan=first.authoritative_plan,
    )
    return first, second


def _publish_initial(runtime: SessionAgentRuntime):
    first, _ = _plans()
    refs = runtime.publish_router_decision(
        route_payload=first.route_plan.to_dict(),
        plan=first.authoritative_plan,
    )
    return first, refs


def test_role_phase_permission_matrix_is_minimal_and_isolates_candidates():
    solve = permission_for("AlternativeSolver", "solve_alternative")
    review = permission_for("AlternativeSolver", "peer_review_candidate")

    assert "PlanArtifact" in solve.readable_artifact_types
    assert "CandidateArtifact" not in solve.readable_artifact_types
    assert "CandidateArtifact" in solve.writable_artifact_types
    assert "CandidateArtifact" in review.readable_artifact_types
    assert "PeerReviewArtifact" in review.writable_artifact_types


def test_router_broadcasts_plan_and_each_solver_first_turn_consumes_it():
    runtime = SessionAgentRuntime("b" * 32, AgentRegistry.default())
    _, refs = _publish_initial(runtime)
    plan_artifact_id = refs["plan_artifact_id"]
    messages = runtime.mailbox.snapshot()["messages"]
    recipients = {
        runtime.agents.instance(item["recipient_agent_id"]).role
        for item in messages
        if item["message_type"] == "plan_published"
    }
    assert recipients == {"PrimarySolver", "AlternativeSolver"}

    primary = runtime.begin_model_turn(
        stage="primary",
        turn_kind="solver_progress",
        agent_hint="PrimarySolver:primary-1",
    )
    alternative = runtime.begin_model_turn(
        stage="alternative",
        turn_kind="solver_progress",
        agent_hint="AlternativeSolver:alternative-1",
    )
    assert plan_artifact_id in primary.input_artifact_ids
    assert plan_artifact_id in alternative.input_artifact_ids
    receipts = runtime.mailbox.snapshot()["message_consumptions"]
    assert {item["consumer_agent_id"] for item in receipts} == {
        primary.agent_id,
        alternative.agent_id,
    }


def test_candidate_isolation_is_enforced_before_peer_review_phase():
    runtime = SessionAgentRuntime("i" * 32, AgentRegistry.default())
    _publish_initial(runtime)
    primary = runtime.begin_model_turn(
        stage="primary",
        turn_kind="solver_candidate_standard",
        agent_hint="PrimarySolver:primary-1",
    )
    publication = runtime.complete_model_turn(primary.turn_id, "candidate")

    with pytest.raises(PermissionError, match="phase cannot read"):
        runtime.begin_model_turn(
            stage="alternative",
            turn_kind="solver_candidate_standard",
            agent_hint="AlternativeSolver:alternative-1",
            input_artifact_ids=(publication["output_artifact_id"],),
        )


def test_replan_requires_explicit_solver_acks_and_rejects_stale_turns():
    runtime = SessionAgentRuntime("r" * 32, AgentRegistry.default())
    first, _ = _publish_initial(runtime)
    old_turn = runtime.begin_model_turn(
        stage="primary",
        turn_kind="solver_progress",
        agent_hint="PrimarySolver:primary-1",
    )
    runtime.mark_dispatched(old_turn.turn_id)
    second = RouterPlanner().plan_authoritative(
        ProblemParser().parse(
            "Prove that x^2 is nonnegative for every real x."
        ),
        previous_plan=first.authoritative_plan,
    )
    runtime.publish_router_decision(
        route_payload=second.route_plan.to_dict(),
        plan=second.authoritative_plan,
    )
    barrier = runtime.replan_barrier
    assert barrier is not None
    assert barrier["status"] == "paused"
    assert barrier["acknowledged_agent_ids"] == []

    for agent_id in barrier["required_agent_ids"]:
        runtime.acknowledge_replan(agent_id, second.authoritative_plan.version)
    runtime.resume_replan()
    with pytest.raises(RuntimeError, match="stale Solver Turn"):
        runtime.complete_model_turn(old_turn.turn_id, "stale")


def test_send_message_uses_the_declared_business_recipient_and_message_type():
    context = TurnContext(
        "agent-primary",
        "PrimarySolver",
        "solve",
        "task-1",
        "solve_primary",
        "turn-1",
        "solver_progress",
        "ProgressArtifact",
        "progress_shared",
        "RouterPlanner",
    )
    payload = AgentTurnPayload(
        "1.0",
        "ProgressArtifact",
        "send_message",
        {"claims": []},
        {},
        (
            {
                "recipient_role": "AlternativeSolver",
                "message_type": "progress_shared",
            },
        ),
        "Share a public branch invariant.",
        "",
    )

    handler = ActionRegistry().resolve(context, payload)
    assert handler.recipient_role == "AlternativeSolver"
    assert handler.message_type == "progress_shared"


def test_send_message_is_published_and_delivered_to_the_declared_agent():
    runtime = SessionAgentRuntime("m" * 32, AgentRegistry.default())
    turn = runtime.begin_model_turn(
        stage="primary",
        turn_kind="solver_progress",
        agent_hint="PrimarySolver:primary-1",
    )
    response = json.dumps(
        {
            "protocol_version": "1.0",
            "task_result_type": "ProgressArtifact",
            "action": "send_message",
            "public_state_delta": {"claims": []},
            "result_payload": {},
            "outbound_intents": [
                {
                    "recipient_role": "AlternativeSolver",
                    "message_type": "progress_shared",
                }
            ],
            "progress_summary": "Share a public invariant.",
            "stop_reason": "",
        }
    )

    lineage = runtime.complete_model_turn(
        turn.turn_id,
        response,
        agent_action_protocol=True,
    )
    message = next(
        item
        for item in runtime.mailbox.snapshot()["messages"]
        if item["message_id"] == lineage["message_id"]
    )
    assert runtime.agents.instance(message["recipient_agent_id"]).role == (
        "AlternativeSolver"
    )
    assert message["message_type"] == "progress_shared"


def test_role_allowed_action_is_still_rejected_outside_its_phase():
    runtime = SessionAgentRuntime("p" * 32, AgentRegistry.default())
    turn = runtime.begin_model_turn(
        stage="primary",
        turn_kind="solver_progress",
        agent_hint="PrimarySolver:primary-1",
    )
    response = json.dumps(
        {
            "protocol_version": "1.0",
            "task_result_type": "PeerReviewArtifact",
            "action": "challenge_candidate",
            "public_state_delta": {},
            "result_payload": {"findings": []},
            "outbound_intents": [],
            "progress_summary": "Improper early review.",
            "stop_reason": "",
        }
    )

    with pytest.raises(PermissionError, match="phase cannot perform"):
        runtime.complete_model_turn(
            turn.turn_id,
            response,
            agent_action_protocol=True,
        )


def test_execution_context_hashes_cover_the_actual_shared_and_branch_payloads():
    runtime = SessionAgentRuntime("h" * 32, AgentRegistry.default())
    _publish_initial(runtime)
    effective = runtime.effective_execution_plan
    shared = {"problem": "x^2 >= 0", "plan_id": effective.plan_id}
    branches = {
        item.branch_id: {
            "method_family": item.method_family,
            "visible_context": f"context-for-{item.branch_id}",
        }
        for item in effective.solver_branches
    }

    updated = runtime.bind_execution_contexts(
        shared_context=shared,
        branch_contexts=branches,
    )
    assert {item.shared_context_hash for item in updated.solver_branches} == {
        stable_payload_hash(shared)
    }
    for item in updated.solver_branches:
        assert item.branch_context_hash == stable_payload_hash(
            branches[item.branch_id]
        )


def test_protocol_sequence_preserves_actual_cross_component_order():
    runtime = SessionAgentRuntime("s" * 32, AgentRegistry.default())
    _publish_initial(runtime)
    turn = runtime.begin_model_turn(
        stage="primary",
        turn_kind="solver_candidate_standard",
        agent_hint="PrimarySolver:primary-1",
    )
    runtime.mark_dispatched(turn.turn_id)
    runtime.complete_model_turn(turn.turn_id, "candidate")
    snapshot = runtime.finalize([{"turn_id": turn.turn_id}])
    sequence = snapshot["protocol_sequence"]

    assert [item["sequence"] for item in sequence] == list(
        range(1, len(sequence) + 1)
    )
    event_types = [item["event_type"] for item in sequence]
    assert event_types.index("message_consumed") < event_types.index(
        "model_turn_started"
    )
    assert event_types.index("model_turn_dispatched") < event_types.index(
        "artifact_published",
        event_types.index("model_turn_dispatched"),
    )
    assert event_types[-1] == "agent_stopped"


def test_agent_prompt_versions_are_loaded_from_contract_frontmatter():
    definitions = AgentRegistry.default()
    contracts = PromptContractLoader()
    for role in definitions.roles():
        definition = definitions.get(role)
        assert definition.prompt_version == contracts.load(
            definition.prompt_contract
        ).fields["version"]


def test_send_message_rejects_undeclared_or_ambiguous_business_intents():
    context = TurnContext(
        "agent-primary",
        "PrimarySolver",
        "solve",
        "task-1",
        "solve_primary",
        "turn-1",
        "solver_progress",
        "ProgressArtifact",
        "progress_shared",
        "RouterPlanner",
    )
    payload = AgentTurnPayload(
        "1.0",
        "ProgressArtifact",
        "send_message",
        {"claims": []},
        {},
        ({"recipient_role": "AlternativeSolver"},),
        "Ambiguous message.",
        "",
    )
    with pytest.raises(ValueError, match="business intent"):
        ActionRegistry().resolve(context, payload)
