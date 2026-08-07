from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from llm_client import DEFAULT_MODEL
from mathforge.agents.router_planner import RouterRuleEngine
from mathforge.agents.solver import PrimarySolver, SolverExecutor, SolverRequest
from mathforge.evaluation.scoring import score_response
from mathforge.harness.budget import CallBudget
from mathforge.harness.errors import ModelResponseError, ModelTransportError
from mathforge.harness.provider import ModelCallGate, OfficialClientProvider
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.parsing.solution_parser import SolutionParser
from scripts.build_phase0_baseline import build_manifest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "phase0_baseline_manifest.json"
MULTI_AGENT_BASELINE = ROOT / "data" / "true_multi_agent_phase0_baseline.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    ("expected", "actual"),
    [
        (r"\pi^2/6-(\ln2)^2", r"Final answer: \frac{\pi^2}{6}-(\ln2)^2"),
        (r"8\pi^6/63", r"Final answer: \frac{8\pi^6}{63}"),
    ],
)
def test_symbolic_equivalence_baseline_canaries(expected, actual):
    result = score_response(
        expected,
        actual,
        answer_type="expression",
        scorer="symbolic",
    )
    assert result.scored and result.correct


def test_baseline_manifest_is_reproducible_and_has_all_failure_families():
    persisted = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert persisted == build_manifest()
    assert {
        item["name"]: item["case_count"] for item in persisted["datasets"]
    } == {
        "reliability": 5,
        "general_high_difficulty": 12,
        "contract_adversarial": 6,
    }
    assert set(persisted["failure_taxonomy"]) == {
        "transport",
        "schema",
        "logic",
        "verification",
        "formatting",
    }


@pytest.mark.parametrize(
    ("behavior", "expected_code"),
    [
        (ConnectionError("connection refused"), "network_connect_failure"),
        (RuntimeError("ReadTimeout"), "network_read_timeout"),
        ("", "empty_response"),
    ],
)
def test_reliability_transport_injections_are_typed(behavior, expected_code):
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


def test_reliability_schema_injection_is_distinct_from_transport():
    class InvalidSchemaClient:
        def chat(self, **_kwargs):
            return "{}"

    problem = ProblemParser().parse("Compute 1+1.")
    route = RouterRuleEngine().plan(problem)
    request = SolverRequest(
        candidate_id="invalid-schema",
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


def test_true_multi_agent_phase0_registry_is_reproducible():
    baseline = json.loads(MULTI_AGENT_BASELINE.read_text(encoding="utf-8"))
    assert baseline["schema_version"] == "1.0"
    assert baseline["phase"] == "F0"
    assert baseline["status"] == "governance-frozen-runtime-unmodified"
    assert baseline["review_source_commit"] == (
        "b5a743426a85c7d843215dec590497a61f0067f2"
    )

    plan = baseline["authoritative_plan"]
    assert _sha256(ROOT / plan["path"]) == plan["sha256"]

    runtime = baseline["runtime_baseline"]
    assert _sha256(ROOT / runtime["snapshot_path"]) == runtime["sha256"]
    snapshot = json.loads(
        (ROOT / runtime["snapshot_path"]).read_text(encoding="utf-8")
    )
    assert snapshot["max_model_calls"] == runtime["max_model_calls"] == 6
    assert snapshot["enable_router"] is runtime["enable_router"] is False
    assert snapshot["status"] == runtime["status"] == "candidate-unvalidated"

    for artifact in (
        baseline["content_baseline"]["phase0_dataset_manifest"],
        baseline["content_baseline"]["content_review_manifest"],
        baseline["content_baseline"]["build_provenance_manifest"],
    ):
        assert _sha256(ROOT / artifact["path"]) == artifact["sha256"]


def test_prompt_skill_and_model_identity_match_frozen_governance_sources():
    baseline = json.loads(MULTI_AGENT_BASELINE.read_text(encoding="utf-8"))
    review = json.loads(
        (ROOT / "docs" / "content_review_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    scopes = {item["id"]: item for item in review["scopes"]}
    content = baseline["content_baseline"]

    assert content["prompt_contracts"]["sha256"] == scopes["prompt-contracts"][
        "sha256"
    ]
    assert content["prompt_contracts"]["count"] == scopes["prompt-contracts"][
        "expected_count"
    ]
    assert content["prompt_compiler"]["sha256"] == scopes["prompt-compiler"][
        "sha256"
    ]
    assert content["domain_skills"]["sha256"] == scopes["domain-skills"][
        "sha256"
    ]
    assert content["general_skills"]["sha256"] == scopes["general-skills"][
        "sha256"
    ]

    identity = baseline["model_identity"]
    assert identity["default_requested_model"] == DEFAULT_MODEL
    assert identity["response_model_observable"] is False
    assert identity["thinking_mode_observable"] is False


def test_f0_freezes_target_definition_without_claiming_runtime_completion():
    baseline = json.loads(MULTI_AGENT_BASELINE.read_text(encoding="utf-8"))
    target = baseline["target_design"]
    assert target["implementation_status"] == "not-started-after-f0"
    assert target["case_max_concurrency"] == 3
    assert target["model_requests_per_minute"] == 200
    assert target["initial_max_logical_model_calls_per_problem"] == 48
    assert target["soft_call_checkpoints"] == [16, 28, 40]
    assert target["closure_reserve_calls"] == 8
    assert target["router_llm_required"] is True
    assert target["minimum_independent_solver_agents"] == 2

    plan = (ROOT / baseline["authoritative_plan"]["path"]).read_text(
        encoding="utf-8"
    )
    legacy = (ROOT / baseline["superseded_plan"]["path"]).read_text(
        encoding="utf-8"
    )
    assert "## 39. 最终 Definition of Done" in plan
    assert "## 27. Phase F0：基线与治理" in plan
    assert "Superseded Design History" in legacy
    assert "每题六次调用”不再是目标架构" in legacy
