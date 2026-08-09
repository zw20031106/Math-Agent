from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import re

import pytest

from mathforge.agent_runtime.definitions import AgentRegistry
from mathforge.agent_runtime.runtime import SessionAgentRuntime
from mathforge.agents.router_planner import RouterPlanner
from mathforge.config import HarnessConfig
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.runtime import MathForgeHarness
from tests.test_phase2_concurrency_lifecycle import _minimal_config


def _router_payload(
    *,
    method: str = "structural-transform",
) -> dict:
    alternative_method = (
        "constructive-computation"
        if method != "constructive-computation"
        else "direct-deduction"
    )
    return {
        "primary_domain": "general-math",
        "secondary_domain": None,
        "risk": "medium",
        "patterns": ["decisive-relation"],
        "preferred_methods": [method],
        "alternative_methods": [alternative_method],
        "needs_long_horizon": False,
    }


class RouterAwareClient:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = list(payloads)
        self.roles: list[str] = []
        self.solver_prompts: list[str] = []

    def chat(self, *, messages, temperature, max_tokens) -> str:
        system = messages[0]["content"]
        self.roles.append(system.split(".", 1)[0])
        if system.startswith("You are RouterPlanner"):
            return json.dumps(self.payloads.pop(0), ensure_ascii=False)
        prompt = messages[-1]["content"]
        self.solver_prompts.append(prompt)
        match = re.search(r"Required core method family: ([a-z-]+)\.", prompt)
        method = match.group(1) if match else "direct-deduction"
        return json.dumps(
            {
                "method": method,
                "final_answer": "4",
                "public_solution_steps": ["$2+2=4$"],
                "claims": [
                    {
                        "claim_id": "c1",
                        "statement": "$2+2=4$",
                        "depends_on": [],
                        "check_type": "reasoning",
                        "importance": "critical",
                    }
                ],
                "solution_text": "$2+2=4$",
                "assumptions": [],
                "theorems": [],
                "unresolved_obligations": [],
            }
        )


class RouterFailureClient(RouterAwareClient):
    def __init__(self) -> None:
        super().__init__([])
        self._failed = False

    def chat(self, *, messages, temperature, max_tokens) -> str:
        if (
            messages[0]["content"].startswith("You are RouterPlanner")
            and not self._failed
        ):
            self._failed = True
            self.roles.append("You are RouterPlanner")
            raise RuntimeError("simulated router transport failure")
        return super().chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )


def _router_config() -> HarnessConfig:
    return _minimal_config(max_model_calls=2, enable_router=True)


def test_router_is_first_model_call_and_has_distinct_agent_identity():
    client = RouterAwareClient([_router_payload()])
    result = MathForgeHarness(client, _router_config()).solve("Compute 2+2.", {})
    budget = next(
        event for event in result["trace"] if event["event"] == "budget_summary"
    )
    records = budget["model_call_records"]
    assert [record["stage"] for record in records] == ["router", "primary"]
    assert records[0]["agent_id"] != records[1]["agent_id"]
    assert records[0]["agent_role"] == "RouterPlanner"
    assert records[1]["agent_role"] == "PrimarySolver"


def test_router_intent_causally_configures_host_plan_and_solver():
    client = RouterAwareClient([_router_payload(method="spectral")])
    result = MathForgeHarness(client, _router_config()).solve("Compute 2+2.", {})
    route = next(
        event for event in result["trace"] if event["event"] == "route_planned"
    )
    budget = next(
        event for event in result["trace"] if event["event"] == "budget_summary"
    )
    protocol = next(
        event for event in result["trace"] if event["event"] == "agent_protocol"
    )
    solver_call = budget["model_call_records"][1]
    assert route["router_source"] == "llm_router"
    assert route["method_families"][0] == "spectral"
    assert route["route_artifact_id"] and route["plan_artifact_id"]
    assert "Required core method family: spectral." in client.solver_prompts[0]
    assert solver_call["plan_id"] == route["plan_id"]
    assert solver_call["subgoal_ids"] == ["sg-1"]
    assert solver_call["planned_method_family"] == "spectral"
    artifact_types = {item["artifact_type"] for item in protocol["artifacts"]}
    assert {"RouteArtifact", "PlanArtifact"} <= artifact_types
    assert any(
        message["message_id"] == route["plan_message_id"]
        and route["plan_artifact_id"] in message["artifact_ids"]
        for message in protocol["messages"]
    )


def test_router_transport_failure_uses_real_rule_fallback_then_runs_solver():
    client = RouterFailureClient()
    result = MathForgeHarness(client, _router_config()).solve("Compute 2+2.", {})
    route = next(
        event for event in result["trace"] if event["event"] == "route_planned"
    )
    budget = next(
        event for event in result["trace"] if event["event"] == "budget_summary"
    )
    assert route["router_llm_attempted"] is True
    assert route["router_source"] == "router_rule_fallback"
    assert route["router_fallback_reason"].startswith("router_")
    assert [record["stage"] for record in budget["model_call_records"]] == [
        "router",
        "primary",
    ]
    assert budget["model_call_records"][0]["status"] == "failed"
    assert budget["model_call_records"][1]["status"] == "completed"
    assert result["run_metrics"]["outcome"] == "primary"


@pytest.mark.parametrize(
    ("payload", "failure_code"),
    [
        (
            _router_payload(method="not-a-method"),
            "router_method_invalid",
        ),
        (
            {**_router_payload(), "task_proposals": []},
            "router_schema_invalid",
        ),
    ],
)
def test_invalid_router_intent_uses_explicit_rule_fallback(
    payload,
    failure_code,
):
    outcome = RouterPlanner().plan_authoritative(
        ProblemParser().parse("Compute 2+2."),
        llm_chat=lambda **_: json.dumps(payload),
        consume_call=lambda: None,
    )
    assert outcome.llm_attempted is True
    assert outcome.source == "router_rule_fallback"
    assert outcome.fallback_reason == failure_code
    outcome.authoritative_plan.validate()


def test_router_can_run_again_after_failed_turn_state_is_released():
    runtime = SessionAgentRuntime("r" * 32, AgentRegistry.default())
    first = runtime.begin_model_turn(
        stage="router",
        turn_kind="router",
        agent_hint="RouterPlanner",
    )
    runtime.mark_dispatched(first.turn_id)
    runtime.fail_model_turn(first.turn_id, "provider_5xx")
    second = runtime.begin_model_turn(
        stage="router",
        turn_kind="replan",
        agent_hint="RouterPlanner",
    )
    runtime.mark_dispatched(second.turn_id)
    assert second.agent_id == first.agent_id
    assert second.turn_id != first.turn_id


def test_replan_versions_plan_and_preserves_conditions_and_verified_facts():
    problem = ProblemParser().parse(
        "Given x is positive, compute x+x under the stated condition."
    )
    router = RouterPlanner()
    payloads = iter(
        [
            _router_payload(method="direct-deduction"),
            _router_payload(method="structural-transform"),
        ]
    )
    first = router.plan_authoritative(
        problem,
        llm_chat=lambda **_: json.dumps(next(payloads)),
        consume_call=lambda: None,
    )
    second = router.plan_authoritative(
        problem,
        llm_chat=lambda **_: json.dumps(next(payloads)),
        consume_call=lambda: None,
        previous_plan=first.authoritative_plan,
        verified_fact_ids=("fact-positive-x",),
    )
    assert second.authoritative_plan.version == 2
    assert second.authoritative_plan.parent_plan_id == first.authoritative_plan.plan_id
    assert (
        second.authoritative_plan.original_condition_digest
        == first.authoritative_plan.original_condition_digest
    )
    assert (
        second.authoritative_plan.preserved_conditions
        == first.authoritative_plan.preserved_conditions
    )
    assert "Given x is positive" in second.authoritative_plan.preserved_conditions
    assert second.authoritative_plan.verified_fact_ids == ("fact-positive-x",)
    runtime = SessionAgentRuntime("p" * 32, AgentRegistry.default())
    runtime.bind_authoritative_plan(first.authoritative_plan)
    first_task = runtime.begin_model_turn(
        stage="primary",
        turn_kind="solver_candidate_standard",
        agent_hint="PrimarySolver:primary-1",
    )
    runtime.bind_authoritative_plan(second.authoritative_plan)
    second_task = runtime.begin_model_turn(
        stage="primary",
        turn_kind="solver_candidate_standard",
        agent_hint="PrimarySolver:primary-1",
    )
    assert second_task.task_id != first_task.task_id
    assert second_task.plan_id == second.authoritative_plan.plan_id


def test_production_profiles_cannot_disable_or_starve_router():
    for profile in ("competition", "balanced", "safe"):
        config = HarnessConfig.from_json(Path(f"config/{profile}.json"))
        assert config.enable_router is True
        assert config.max_model_calls >= 2
    with pytest.raises(ValueError, match="require the authoritative Router"):
        replace(
            HarnessConfig.from_json(Path("config/competition.json")),
            enable_router=False,
        )
