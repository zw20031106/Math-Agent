from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from mathforge.agents.router_planner import RouterRuleEngine
from mathforge.agents.solver import PrimarySolver, SolverExecutor, SolverRequest
from mathforge.config import HarnessConfig
from mathforge.evaluation.scoring import score_response
from mathforge.harness.adaptive_fanout import AdaptiveFanoutPolicy
from mathforge.harness.budget import CallBudget
from mathforge.harness.errors import (
    BudgetExceeded,
    ModelResponseError,
    ModelTransportError,
)
from mathforge.harness.provider import ModelCallGate, OfficialClientProvider
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.parsing.solution_parser import SolutionParser
from mathforge.runtime import MathForgeHarness
from scripts.build_phase0_baseline import build_manifest


ROOT = Path(__file__).resolve().parents[1]
BASELINE_MANIFEST = ROOT / "data" / "phase0_baseline_manifest.json"


@pytest.mark.parametrize(
    ("expected", "actual"),
    [
        (
            r"\pi^2/6-(\ln2)^2",
            r"Final answer: \frac{\pi^2}{6}-(\ln2)^2",
        ),
        (
            r"8\pi^6/63",
            r"Final answer: \frac{8\pi^6}{63}",
        ),
    ],
)
def test_phase0_symbolic_equivalence_canaries_are_exact(expected, actual):
    result = score_response(
        expected,
        actual,
        answer_type="expression",
        scorer="symbolic",
    )

    assert result.scored is True
    assert result.correct is True
    assert result.reason == "symbolic_equivalent"


def test_phase0_baseline_manifest_is_reproducible_and_private():
    persisted = json.loads(BASELINE_MANIFEST.read_text(encoding="utf-8"))
    rebuilt = build_manifest()
    rebuilt["config"] = persisted["config"]
    serialized = json.dumps(persisted, ensure_ascii=False)

    assert persisted == rebuilt
    assert {
        record["name"]: record["case_count"]
        for record in persisted["datasets"]
    } == {
        "reliability": 5,
        "general_high_difficulty": 12,
        "contract_adversarial": 6,
    }
    assert persisted["historical_reliability_snapshot"][
        "known_failure_classes"
    ] == ["network_connect_failure"]
    assert set(persisted["failure_taxonomy"]) == {
        "transport",
        "schema",
        "logic",
        "verification",
        "formatting",
    }
    assert "sk-" not in serialized
    assert "Authorization" not in serialized
    assert "D:\\" not in serialized


@pytest.mark.parametrize(
    ("behavior", "expected_code"),
    [
        (ConnectionError("connection refused"), "network_connect_failure"),
        (RuntimeError("ReadTimeout"), "network_read_timeout"),
        ("", "empty_response"),
    ],
)
def test_phase0_reliability_transport_injections_are_typed(
    behavior,
    expected_code,
):
    class InjectedClient:
        def chat(self, **_kwargs):
            if isinstance(behavior, BaseException):
                raise behavior
            return behavior

    with pytest.raises(ModelTransportError) as captured:
        OfficialClientProvider(InjectedClient(), ModelCallGate(1)).chat(
            messages=[{"role": "user", "content": "test"}],
            temperature=0.0,
            max_tokens=16,
        )

    assert captured.value.code == expected_code


def test_phase0_schema_injection_has_a_distinct_candidate_failure_code():
    class InvalidSchemaClient:
        def chat(self, **_kwargs):
            return "{}"

    problem = ProblemParser().parse("Compute 1+1.")
    route = RouterRuleEngine().plan(problem)
    request = SolverRequest(
        candidate_id="phase0-invalid-schema",
        problem=problem,
        route=route,
        skill_context="",
        method_family=route.method_families[0],
    )

    with pytest.raises(ModelResponseError) as captured:
        SolverExecutor(
            OfficialClientProvider(InvalidSchemaClient(), ModelCallGate(1)),
            SolutionParser(),
        ).execute(
            PrimarySolver(),
            request,
            CallBudget(max_calls=2),
            temperature=0.0,
            max_tokens=512,
        )

    assert captured.value.code == "candidate_schema_invalid"


def test_phase1_resource_replan_never_retracts_consumed_global_calls():
    budget = CallBudget(max_calls=4)
    initial = budget.resource_governor.activation_plan(
        used_calls=0,
        router_calls=0,
        candidate_count=1,
        verifier_required=False,
        repair_requested=False,
        lemma_requested=False,
        finalizer_requested=False,
    )
    assert initial.primary == 1
    budget.consume(stage="primary")
    budget.consume(stage="primary", optional=True)

    replacement = budget.resource_governor.activation_plan(
        used_calls=budget.used_calls,
        router_calls=0,
        candidate_count=1,
        verifier_required=True,
        repair_requested=True,
        lemma_requested=False,
        finalizer_requested=False,
        reverification_requested=True,
    )
    snapshot = budget.snapshot()
    assert replacement.max_calls == 4
    assert snapshot.remaining_calls == 2
    budget.consume(stage="verifier")
    budget.consume(stage="verifier")
    with pytest.raises(BudgetExceeded, match="call budget exhausted"):
        budget.consume(stage="repair")


def test_phase1_low_risk_route_keeps_one_lazy_reliability_standby():
    problem = ProblemParser().parse("Compute 1+1.")
    route = RouterRuleEngine().plan(problem)
    route.candidate_count = 2
    route.risk_level = "low"
    budget = CallBudget(max_calls=3)

    decision = AdaptiveFanoutPolicy().decide(
        route,
        None,
        budget,
        required_stage_reserve=0,
    )

    assert decision.admitted_candidates == 2
    assert "reliability_standby" in decision.reason_codes


def test_phase1_ordinary_provider_failures_update_health_without_secrets():
    class FailingClient:
        def chat(self, **_kwargs):
            raise RuntimeError("503 server error bearer sk-do-not-leak")

    gate = ModelCallGate(1)
    provider = OfficialClientProvider(FailingClient(), gate)
    for _ in range(2):
        with pytest.raises(ModelTransportError) as captured:
            provider.chat(
                messages=[{"role": "user", "content": "test"}],
                temperature=0.0,
                max_tokens=16,
            )
        assert captured.value.code == "provider_5xx"
        assert "sk-do-not-leak" not in str(captured.value)

    health = gate.health_snapshot()
    assert health["state"] == "degraded"
    assert health["ordinary_failure_count"] == 2
    assert health["consecutive_failures"] == 2


def test_phase1_degraded_unbound_provider_state_does_not_leak_into_case():
    harness = MathForgeHarness(_ValidClient(), _minimal_config(max_model_calls=3))
    for _ in range(3):
        harness._model_gate.record_provider_result(
            success=False,
            failure_code="provider_5xx",
        )

    result = harness.solve("Compute the derivative of x^2.", {"idx": "health"})

    policy_events = [
        event
        for event in result["trace"]
        if event.get("event") == "resource_plan_updated"
        and event.get("reason") == "provider_degraded"
    ]
    assert policy_events == []
    assert result["final_response"].strip()
    assert harness._model_gate.health_snapshot()["state"] == "degraded"


def test_phase1_primary_two_failures_use_standby_and_return_answer():
    client = _FailTwiceThenValidClient()
    harness = MathForgeHarness(client, _minimal_config(max_model_calls=3))

    result = harness.solve("Compute 1+1.", {"idx": "phase1-standby"})

    assert client.calls == 3
    assert "2" in result["final_response"]
    assert result["run_metrics"]["outcome"] == "primary"
    decision = next(
        event
        for event in result["trace"]
        if event.get("event") == "adaptive_fanout_decided"
    )
    assert "primary_unavailable" in decision["reason_codes"]
    assert not any(
        event.get("event") == "fallback_used"
        for event in result["trace"]
    )


def test_low_risk_primary_still_runs_independent_alternative_backbone():
    client = _ValidClient()
    harness = MathForgeHarness(client, _minimal_config(max_model_calls=3))

    result = harness.solve(
        "Compute the derivative of x^2.",
        {"idx": "phase1-low-risk"},
    )

    transport = next(
        event
        for event in result["trace"]
        if event["event"] == "model_transport_completed"
    )
    roles = [item["role"] for item in transport["calls"]]
    assert roles.count("PrimarySolver") == 1
    assert roles.count("AlternativeSolver") == 1
    decision = next(
        event
        for event in result["trace"]
        if event.get("event") == "adaptive_fanout_decided"
    )
    assert decision["admitted_candidates"] == 2


def test_phase1_downstream_failure_salvages_last_safe_candidate(monkeypatch):
    harness = MathForgeHarness(
        _ValidClient(),
        _minimal_config(max_model_calls=2),
    )

    def fail_format(*_args, **_kwargs):
        raise RuntimeError("downstream formatter failure")

    monkeypatch.setattr(harness._formatter, "format", fail_format)
    result = harness.solve("Compute 1+1.", {"idx": "phase1-salvage"})

    assert result["run_metrics"]["error_code"] == "degraded_candidate_salvage"
    assert result["run_metrics"]["outcome"] == "primary"
    assert result["run_metrics"]["final_phase"] == "completed"
    assert result["final_response"].strip() == "2"
    assert any(
        event.get("event") == "candidate_salvaged"
        for event in result["trace"]
    )
    assert not any(
        event.get("event") == "fallback_used"
        for event in result["trace"]
    )


def test_phase1_hard_gate_rejection_never_salvages_that_candidate(monkeypatch):
    config = _minimal_config(max_model_calls=2)
    config = HarnessConfig(
        **{
            **config.to_dict(),
            "enable_evidence": True,
        }
    )
    harness = MathForgeHarness(_ValidClient(), config)

    class RejectedGate:
        accepted = []
        rejected_candidate_ids = ["primary-1"]

    monkeypatch.setattr(
        harness._evidence_stage,
        "hard_gate",
        lambda *_args, **_kwargs: RejectedGate(),
    )
    result = harness.solve("Compute 1+1.", {"idx": "phase1-hard-reject"})

    assert result["run_metrics"]["outcome"] == "fallback"
    assert any(
        event.get("event") == "fallback_used"
        for event in result["trace"]
    )
    assert not any(
        event.get("event") == "candidate_salvaged"
        for event in result["trace"]
    )


def _minimal_config(*, max_model_calls: int) -> HarnessConfig:
    return HarnessConfig(
        profile="phase1-test",
        status="test",
        max_model_calls=max_model_calls,
        enable_router=False,
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
    )


def _candidate_response(messages) -> str:
    content = messages[-1]["content"]
    method_match = re.search(
        r"Required core method family: ([a-z-]+)\.",
        content,
    )
    method = (
        method_match.group(1)
        if method_match is not None
        else "direct-deduction"
    )
    return json.dumps(
        {
            "method": method,
            "final_answer": "2",
            "public_solution_steps": ["Adding one and one gives two."],
            "claims": [
                {
                    "claim_id": "c1",
                    "statement": "1+1=2.",
                    "depends_on": [],
                    "check_type": "reasoning",
                    "importance": "critical",
                }
            ],
            "method_steps": [
                {
                    "step_id": "s1",
                    "kind": "conclusion",
                    "claim_ids": ["c1"],
                    "theorem": "",
                }
            ],
            "solution_text": "Adding one and one gives two.",
            "assumptions": [],
            "theorems": [],
            "unresolved_obligations": [],
        }
    )


class _ValidClient:
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, *, messages, temperature, max_tokens) -> str:
        del temperature, max_tokens
        self.calls += 1
        return _candidate_response(messages)


class _FailTwiceThenValidClient(_ValidClient):
    def chat(self, *, messages, temperature, max_tokens) -> str:
        del temperature, max_tokens
        self.calls += 1
        if self.calls <= 2:
            raise RuntimeError("503 server error")
        return _candidate_response(messages)
