from __future__ import annotations

import json
from pathlib import Path

import pytest

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
