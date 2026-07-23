from __future__ import annotations

import json

import pytest

from mathforge.agents.router_planner import RouterRuleEngine
from mathforge.harness.schemas import (
    CandidateSolution,
    ProblemIR,
    RoutePlan,
    SchemaValidationError,
)
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.parsing.solution_parser import SolutionParser


def _parse(payload: dict) -> CandidateSolution:
    return SolutionParser().parse(
        json.dumps(payload),
        candidate_id="host-candidate",
        role="PrimarySolver",
        answer_type="integer",
    )


def test_host_owns_identity_role_answer_type_plan_and_version():
    candidate = _parse(
        {
            "candidate_id": "model-candidate",
            "role": "AlternativeSolver",
            "answer_type": "text",
            "planned_method_family": "model-plan",
            "version": 999,
            "method": "direct",
            "solution_text": "work",
            "final_answer": "2",
        }
    )
    assert candidate.candidate_id == "host-candidate"
    assert candidate.role == "PrimarySolver"
    assert candidate.answer_type == "integer"
    assert candidate.planned_method_family == ""
    assert candidate.version == 1
    assert {
        "candidate_id:host_owned",
        "role:host_owned",
        "answer_type:host_owned",
        "planned_method_family:host_owned",
        "version:host_owned",
    } <= set(candidate.contract_deviations)


def test_host_owns_claim_verification_fields_and_records_unknown_fields():
    candidate = _parse(
        {
            "solution_text": "work",
            "final_answer": "2",
            "claims": [
                {
                    "claim_id": "step",
                    "statement": "done",
                    "status": "verified",
                    "verification_state": "semantically_verified",
                    "claim_kind": "identity",
                    "unexpected": "ignored",
                }
            ],
        }
    )
    claim = candidate.claims[0]
    assert claim.status == "unverified"
    assert claim.verification_state == "unknown"
    assert claim.claim_kind == "reasoning"
    assert {
        "claims[0].status:host_owned",
        "claims[0].verification_state:host_owned",
        "claims[0].claim_kind:host_owned",
        "claims[0].unexpected:ignored",
    } <= set(candidate.contract_deviations)


def test_string_list_fields_are_not_split_into_characters():
    candidate = _parse(
        {
            "solution_text": "work",
            "final_answer": "2",
            "assumptions": "x > 0",
            "theorems": "Pythagoras",
            "claims": [
                {
                    "claim_id": "step",
                    "statement": "done",
                    "depends_on": "base",
                }
            ],
        }
    )
    assert candidate.assumptions == []
    assert candidate.theorems == []
    assert candidate.claims[0].depends_on == []
    assert "assumptions:type" in candidate.contract_deviations
    assert "theorems:type" in candidate.contract_deviations
    assert "claims[0].depends_on:type" in candidate.contract_deviations


@pytest.mark.parametrize(
    ("claims", "message"),
    [
        (
            [
                {"claim_id": "same", "statement": "a"},
                {"claim_id": "same", "statement": "b"},
            ],
            "duplicate claim id",
        ),
        (
            [
                {
                    "claim_id": "step",
                    "statement": "a",
                    "depends_on": ["missing"],
                }
            ],
            "unknown dependency",
        ),
        (
            [
                {"claim_id": "a", "statement": "a", "depends_on": ["b"]},
                {"claim_id": "b", "statement": "b", "depends_on": ["a"]},
            ],
            "claim dependency cycle",
        ),
    ],
)
def test_invalid_claim_graphs_are_rejected(claims, message):
    with pytest.raises(SchemaValidationError, match=message):
        _parse(
            {
                "solution_text": "work",
                "final_answer": "2",
                "claims": claims,
            }
        )


def test_candidate_schema_round_trips_with_explicit_version():
    candidate = _parse(
        {
            "method": "direct",
            "solution_text": "work",
            "final_answer": "2",
            "claims": [{"claim_id": "step", "statement": "done"}],
        }
    )
    payload = candidate.to_dict()
    restored = CandidateSolution.from_dict(payload)
    assert payload["schema_version"] == CandidateSolution.SCHEMA_VERSION
    assert restored.to_dict() == payload


def test_problem_and_route_contracts_round_trip_without_loose_dicts():
    problem = ProblemParser().parse("Solve x + 1 = 2")
    problem.validate()
    route = RouterRuleEngine().plan(problem)
    route.validate()
    restored_problem = ProblemIR.from_dict(problem.to_dict())
    restored_route = RoutePlan.from_dict(route.to_dict())

    assert restored_problem.to_dict() == problem.to_dict()
    assert restored_route.to_dict() == route.to_dict()


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": "1.0", "raw_problem": []},
        {
            **ProblemParser().parse("x").to_dict(),
            "unexpected": "silent-boundary-crossing",
        },
    ],
)
def test_problem_schema_rejects_malformed_or_unknown_fields(payload):
    with pytest.raises(SchemaValidationError):
        ProblemIR.from_dict(payload)


def test_route_schema_rejects_string_booleans():
    problem = ProblemParser().parse("x")
    payload = RouterRuleEngine().plan(problem).to_dict()
    payload["use_rag"] = "false"
    with pytest.raises(SchemaValidationError, match="use_rag"):
        RoutePlan.from_dict(payload)


def test_oversized_claim_collection_is_rejected():
    with pytest.raises(SchemaValidationError, match="claim count"):
        _parse(
            {
                "solution_text": "work",
                "final_answer": "2",
                "claims": [
                    {"claim_id": f"c{index}", "statement": "x"}
                    for index in range(65)
                ],
            }
        )


@pytest.mark.parametrize(
    "malformed",
    [None, 1, True, "value", {"x": 1}, [1, None, "claim"]],
)
def test_parser_fuzz_has_only_classified_schema_failures(malformed):
    payload = {
        "solution_text": malformed,
        "final_answer": malformed,
        "assumptions": malformed,
        "theorems": malformed,
        "claims": malformed,
        "unresolved_obligations": malformed,
    }
    try:
        _parse(payload)
    except SchemaValidationError:
        pass
