from __future__ import annotations

import pytest

from mathforge.agent_runtime.action_registry import ActionRegistry
from mathforge.agent_runtime.definitions import AgentRegistry
from mathforge.agent_runtime.execution_plan import (
    BranchPlanOverride,
    admit_router_plan,
    build_effective_execution_plan,
)
from mathforge.agent_runtime.protocol import AgentTurnPayload, TurnContext
from mathforge.agent_runtime.runtime import SessionAgentRuntime
from mathforge.agents.router_planner import RouterPlanner
from mathforge.harness.schemas import CandidateSolution, Claim
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.verification.candidate_pool import CandidatePool


def _planning_outcome():
    problem = ProblemParser().parse("Prove that x^2 is nonnegative for every real x.")
    return RouterPlanner().plan_authoritative(problem)


def test_router_host_effective_pipeline_is_the_only_executable_branch_source():
    outcome = _planning_outcome()
    agents = AgentRegistry.default()
    admitted = admit_router_plan(outcome.authoritative_plan, agents)
    effective = build_effective_execution_plan(outcome.authoritative_plan, admitted)

    assert effective.router_plan_id == outcome.authoritative_plan.plan_id
    assert effective.version == outcome.authoritative_plan.version
    assert [item.agent_role for item in effective.solver_branches][:2] == [
        "PrimarySolver",
        "AlternativeSolver",
    ]
    assert all(item.plan_id == outcome.authoritative_plan.plan_id for item in effective.branches)
    assert effective.shared_lemma_policy == "off_until_candidate_backbone"


def test_host_candidate_limit_is_visible_in_admitted_and_effective_plans():
    outcome = _planning_outcome()
    admitted = admit_router_plan(
        outcome.authoritative_plan,
        AgentRegistry.default(),
        candidate_limit=1,
    )
    effective = build_effective_execution_plan(outcome.authoritative_plan, admitted)

    assert len(effective.solver_branches) == 1
    assert effective.solver_branches[0].agent_role == "PrimarySolver"
    assert any("host_candidate_limit" in reason for reason in admitted.admission_reasons)


def test_action_registry_unifies_role_declaration_authorization_and_handler():
    registry = ActionRegistry()
    definitions = AgentRegistry.default()
    context = TurnContext(
        "agent-primary",
        "PrimarySolver",
        "solve",
        "task-1",
        "solve_primary",
        "turn-1",
        "candidate",
        "CandidateArtifact",
        "candidate_published",
        "VerifierSkeptic",
    )
    payload = AgentTurnPayload(
        "1.0",
        "CandidateArtifact",
        "publish_candidate",
        {},
        {"final_answer": "1"},
        (),
        "Published a candidate",
        "candidate complete",
    )

    assert set(definitions.get("PrimarySolver").allowed_action_types) == set(
        registry.actions_for("PrimarySolver")
    )
    handler = registry.resolve(context, payload)
    assert (handler.artifact_type, handler.message_type, handler.recipient_role) == (
        "CandidateArtifact",
        "candidate_published",
        "VerifierSkeptic",
    )
    prohibited = AgentTurnPayload(
        "1.0",
        "CritiqueArtifact",
        "request_repair",
        {},
        {"claim_id": "c1"},
        (),
        "Requested repair",
        "",
    )
    with pytest.raises(ValueError, match="not authorized"):
        registry.resolve(context, prohibited)


def test_replan_barrier_requires_version_matched_ack_and_local_override_is_scoped():
    problem = ProblemParser().parse("Compute x+x.")
    first = RouterPlanner().plan_authoritative(problem)
    second = RouterPlanner().plan_authoritative(
        problem,
        previous_plan=first.authoritative_plan,
    )
    runtime = SessionAgentRuntime("z" * 32, AgentRegistry.default())
    runtime.bind_authoritative_plan(first.authoritative_plan)
    runtime.begin_model_turn(
        stage="primary",
        turn_kind="solver_candidate_standard",
        agent_hint="PrimarySolver:primary-1",
    )
    runtime.bind_authoritative_plan(second.authoritative_plan)
    barrier = runtime.replan_barrier
    assert barrier is not None and barrier["status"] == "paused"
    with pytest.raises(RuntimeError, match="replan ACK barrier"):
        runtime.begin_model_turn(
            stage="primary",
            turn_kind="solver_candidate_standard",
            agent_hint="PrimarySolver:primary-1",
        )
    agent_id = barrier["required_agent_ids"][0]
    with pytest.raises(ValueError, match="version"):
        runtime.acknowledge_replan(agent_id, second.authoritative_plan.version + 1)
    runtime.acknowledge_replan(agent_id, second.authoritative_plan.version)
    runtime.resume_replan()

    effective = runtime.effective_execution_plan
    override = BranchPlanOverride(
        effective.branches[0].branch_id,
        effective.plan_id,
        effective.version,
        1,
        "local-alternative-check",
        "branch-local stall recovery",
    )
    override.validate_against(effective)
    assert runtime.effective_execution_plan == effective


def _candidate(candidate_id: str, role: str) -> CandidateSolution:
    return CandidateSolution(
        candidate_id,
        role,
        "direct-deduction",
        "4",
        "integer",
        claims=[Claim("c1", "2+2=4", importance="critical")],
        planned_method_family="direct-deduction",
    )


def test_non_independent_candidate_remains_viable_with_public_provenance():
    pool = CandidatePool()
    pool.submit(
        _candidate("primary-1", "PrimarySolver"),
        author_agent_id="primary-agent",
        source_turn_id="turn-1",
        candidate_artifact_id="artifact-1",
        provenance={"branch_id": "primarysolver-1", "plan_id": "effective-1", "plan_version": 1},
    )
    duplicate = pool.submit(
        _candidate("alternative-1", "AlternativeSolver"),
        author_agent_id="alternative-agent",
        source_turn_id="turn-2",
        candidate_artifact_id="artifact-2",
        provenance={"branch_id": "alternativesolver-1", "plan_id": "effective-1", "plan_version": 1},
    )

    assert duplicate.independent is False
    assert duplicate.status == "submitted"
    assert duplicate.candidate_id in pool.active_candidate_ids()
    assert duplicate.candidate_id not in {item.candidate_id for item in pool.independent_entries()}
    assert duplicate.plan_id == "effective-1"
    assert duplicate.branch_id == "alternativesolver-1"
