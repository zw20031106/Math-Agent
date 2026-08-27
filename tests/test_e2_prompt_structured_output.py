from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from mathforge.agent_runtime.protocol import (
    AGENT_TURN_FIELDS,
    AgentTurnABExperiment,
    AgentTurnPayloadParser,
    LITE_AGENT_TURN_FIELDS,
    LITE_PROTOCOL_SCHEMA_VERSION,
)
from mathforge.agents.prompt_compiler import (
    CompiledPromptSnapshot,
    PromptCompiler,
)
from mathforge.agents.router_planner import (
    RouterRuleEngine,
    is_simple_direct_candidate,
    simple_direct_candidate_reasons,
)
from mathforge.config import HarnessConfig
from mathforge.harness.budget import CallBudget
from mathforge.harness.metrics import RunMetrics
from mathforge.harness.model_candidate_contract import (
    ModelSemanticPayload,
    model_semantic_payload_example,
)
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.runtime import MathForgeHarness
from tests.fake_client import FakeClient


def _simple_problem_and_route():
    problem = ProblemParser().parse("Compute 2+2.")
    return problem, RouterRuleEngine().plan(problem)


def test_model_semantic_payload_keeps_host_workflow_fields_out():
    payload = ModelSemanticPayload.from_dict(
        {
            "final_answer": "\\boxed{4}",
            "solution_text": "2+2=4",
        }
    )
    assert payload.to_dict() == {
        "final_answer": "\\boxed{4}",
        "solution_text": "2+2=4",
    }
    assert set(model_semantic_payload_example("answer_only")) == {
        "final_answer",
        "solution_text",
    }
    with pytest.raises(ValueError, match="Host-owned"):
        ModelSemanticPayload.from_dict(
            {
                "final_answer": "4",
                "solution_text": "2+2=4",
                "claims": [{"statement": "x", "status": "open"}],
            }
        )


def test_lite_agent_turn_is_strictly_model_owned_and_host_wrapped():
    raw = json.dumps(
        {
            "action": "publish_candidate",
            "payload": {"final_answer": "4", "solution_text": "2+2=4"},
            "outbound": [],
            "stop_reason": "candidate_complete",
        }
    )
    parsed = AgentTurnPayloadParser().parse_lite(raw)
    assert set(parsed.payload.to_dict()) == LITE_AGENT_TURN_FIELDS
    wrapped = parsed.to_agent_turn(
        task_result_type="CandidateArtifact",
        progress_summary="host summary",
    ).payload
    assert wrapped.protocol_version == "1.0"
    assert wrapped.task_result_type == "CandidateArtifact"
    assert wrapped.result_payload == parsed.payload.payload
    assert set(wrapped.to_dict()) == AGENT_TURN_FIELDS
    with pytest.raises(ValueError, match="Host-owned"):
        AgentTurnPayloadParser().parse_lite(
            json.dumps(
                {
                    "action": "publish_candidate",
                    "payload": {
                        "final_answer": "4",
                        "solution_text": "2+2=4",
                        "task_id": "forbidden",
                    },
                    "outbound": [],
                    "stop_reason": "candidate_complete",
                }
            )
        )
    with pytest.raises(ValueError):
        AgentTurnPayloadParser().parse_lite(
            json.dumps(
                {
                    "protocol_version": "1.0",
                    "task_result_type": "CandidateArtifact",
                    "action": "publish_candidate",
                    "public_state_delta": {},
                    "result_payload": {},
                    "outbound_intents": [],
                    "progress_summary": "x",
                    "stop_reason": "candidate_complete",
                }
            )
        )


def test_lite_ab_experiment_migrates_only_after_non_regression():
    experiment = AgentTurnABExperiment()
    experiment.record(
        "P0",
        json_valid=True,
        truncated=False,
        accurate=True,
        output_tokens=100,
        latency_ms=20,
    )
    experiment.record(
        "P1",
        json_valid=True,
        truncated=False,
        accurate=True,
        output_tokens=80,
        latency_ms=15,
    )
    decision = experiment.evaluate()
    assert decision.winner == "P1"
    assert decision.migration_eligible is True
    regressed = AgentTurnABExperiment()
    for variant, accurate, tokens in (("P0", True, 100), ("P1", False, 80)):
        regressed.record(
            variant,
            json_valid=True,
            truncated=False,
            accurate=accurate,
            output_tokens=tokens,
            latency_ms=10,
        )
    assert regressed.evaluate().migration_eligible is False


def test_simple_direct_candidate_eligibility_is_deterministic():
    problem, route = _simple_problem_and_route()
    assert is_simple_direct_candidate(problem, route)
    assert simple_direct_candidate_reasons(problem, route) == ()
    blocked = replace(route, risk_level="high")
    assert not is_simple_direct_candidate(problem, blocked)
    assert "route_risk_high" in simple_direct_candidate_reasons(problem, blocked)


def test_simple_direct_runtime_uses_one_solver_call_without_progress_artifact():
    config = HarnessConfig(
        profile="e2-test",
        status="test",
        max_model_calls=8,
        enable_router=True,
        enable_skills=False,
        enable_alternatives=True,
        enable_tools=False,
        enable_evidence=False,
        enable_proof_obligations=False,
        enable_verifier=False,
        enable_memory=False,
        enable_lemma_loop=False,
        enable_rag=False,
        enable_repair=False,
        enable_finalizer=False,
        enable_long_horizon=True,
        enable_simple_direct_candidate=True,
    )
    client = FakeClient()
    result = MathForgeHarness(client, config).solve("Compute 2+2.", {})
    assert result["run_metrics"]["model_calls"] == 2  # Router + one Solver
    reasoning = next(
        event
        for event in result["trace"]
        if event.get("event") == "reasoning_loop_completed"
    )
    assert reasoning["simple_direct_candidate"] is True
    assert reasoning["progress_turns"] == 0
    assert not any(
        event.get("event") == "autonomous_agent_action"
        and event.get("mode") in {"explore", "continue"}
        for event in result["trace"]
    )


def test_compiled_prompt_snapshot_binds_contract_and_records_components():
    problem, route = _simple_problem_and_route()
    compilation = PromptCompiler().compile_solver(
        "primary_solver",
        problem=problem,
        route=route,
        user_content="Problem: Compute 2+2.",
        autonomous=True,
        protocol_variant=LITE_PROTOCOL_SCHEMA_VERSION,
        semantic_payload=True,
    )
    snapshot = compilation.snapshot()
    assert snapshot.protocol_version == LITE_PROTOCOL_SCHEMA_VERSION
    assert snapshot.max_output_cap == compilation.max_output_tokens
    assert set(snapshot.prompt_component_tokens) == {
        "contract_tokens",
        "runtime_protocol_tokens",
        "skill_tokens",
        "state_tokens",
        "problem_tokens",
        "schema_tokens",
    }
    assert snapshot.to_dict()["output_schema"]["fields"] == list(
        compilation.output_schema_fields
    )
    assert CompiledPromptSnapshot.from_dict(snapshot.to_dict()) == snapshot
    changed_contract = replace(snapshot, contract_sha256="changed")
    with pytest.raises(AssertionError, match="compiled prompt hash"):
        CompiledPromptSnapshot.assert_contract_binding(snapshot, changed_contract)


def test_compiled_prompt_golden_snapshots_cover_roles_and_modes():
    fixture_path = Path(__file__).parent / "fixtures" / "e2_compiled_prompt_snapshots.json"
    expected = json.loads(fixture_path.read_text(encoding="utf-8"))
    problem, route = _simple_problem_and_route()
    compiler = PromptCompiler()
    common = "Problem: Compute 2+2.\n# Skill: general-math\nPublic state: none"
    current = {}
    for role in ("router_planner", "lemma_curator", "verifier_skeptic", "repair", "finalizer"):
        current[f"{role}:role"] = compiler.compile_role(
            role,
            user_content=common,
        ).snapshot().to_dict()
    for role in ("primary_solver", "alternative_solver"):
        current[f"{role}:candidate-lite"] = compiler.compile_solver(
            role,
            problem=problem,
            route=route,
            user_content=common,
            autonomous=True,
            protocol_variant=LITE_PROTOCOL_SCHEMA_VERSION,
            semantic_payload=True,
        ).snapshot().to_dict()
        current[f"{role}:progress-lite"] = compiler.compile_solver_progress(
            role,
            problem=problem,
            route=route,
            user_content=common,
            mode="explore",
            autonomous=True,
            protocol_variant=LITE_PROTOCOL_SCHEMA_VERSION,
        ).snapshot().to_dict()
    for key, snapshot in expected.items():
        assert key in current
        for field in (
            "role_directory",
            "profile",
            "protocol_version",
            "contract_version",
            "contract_sha256",
            "prompt_sha256",
            "output_schema_name",
            "output_schema_fields",
            "selected_skill_summary",
            "max_output_cap",
        ):
            assert current[key][field] == snapshot[field], f"golden mismatch: {key}.{field}"


def test_prompt_component_telemetry_is_recorded_in_budget_and_metrics():
    budget = CallBudget(max_calls=2)
    components = {
        "contract_tokens": 1,
        "runtime_protocol_tokens": 2,
        "skill_tokens": 3,
        "state_tokens": 4,
        "problem_tokens": 5,
        "schema_tokens": 6,
    }
    budget.record_prompt_chars(10, components=components)
    assert budget.to_dict()["prompt_component_tokens"] == components
    metrics = RunMetrics(
        prompt_component_tokens=components,
        outcome="error",
        fallback_used=False,
    )
    assert RunMetrics.from_dict(metrics.to_dict()) == metrics
