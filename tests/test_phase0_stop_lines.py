from __future__ import annotations

import json

from mathforge.tools.executor import ToolExecutor
from mathforge.tools.registry import ToolRegistry, run_tool_direct
from scripts.formal_smoke_fixture import (
    FormalSmokeClient,
    assert_formal_smoke_result,
)
from user_agent import ReasoningAgent


def test_formal_entry_does_not_require_local_model_or_api_environment(monkeypatch):
    monkeypatch.delenv("INTERN_MODEL", raising=False)
    monkeypatch.delenv("INTERN_API_KEY", raising=False)

    result = ReasoningAgent(FormalSmokeClient()).solve(
        "Calculate the integer 1+1",
        {},
    )

    assert_formal_smoke_result(result)


def test_formal_smoke_is_a_true_non_fallback_success(monkeypatch):
    monkeypatch.delenv("INTERN_MODEL", raising=False)
    result = ReasoningAgent(FormalSmokeClient()).solve(
        "Calculate the integer 1+1",
        {"id": "phase0-smoke"},
    )

    assert result["status"] == "success"
    assert "2" in result["final_response"]
    assert all(
        event.get("fallback_used") is not True
        and "fallback" not in str(event.get("event", "")).lower()
        for event in result["trace"]
    )


def test_answer_bearing_metadata_never_reaches_model_or_public_trace():
    canary = "PHASE0_SECRET_ANSWER_CANARY_9173"
    client = FormalSmokeClient()
    result = ReasoningAgent(client).solve(
        "Calculate the integer 1+1",
        {
            "id": "metadata-isolation",
            "label": canary,
            "labels": [canary],
            "benchmark_label": canary,
            "split": canary,
            "answer": canary,
            "reference_answer": canary,
        },
    )

    serialized_messages = json.dumps(client.calls, ensure_ascii=False)
    serialized_trace = json.dumps(result["trace"], ensure_ascii=False)
    assert canary not in serialized_messages
    assert canary not in serialized_trace


def test_finite_enumeration_is_fail_closed_for_empty_and_oversized_inputs():
    empty = run_tool_direct(
        "small_case_enumeration",
        {
            "expression": "n-n",
            "variable": "n",
            "values": [],
            "expected": "0",
        },
    )
    oversized = run_tool_direct(
        "small_case_enumeration",
        {
            "expression": "n-n",
            "variable": "n",
            "values": list(range(129)),
            "expected": "0",
        },
    )

    for result, count in ((empty, 0), (oversized, 129)):
        assert result.status != "pass"
        assert result.payload == {
            "input_count": count,
            "checked_count": 0,
            "truncated": False,
            "counterexamples": [],
        }


def test_finite_enumeration_schema_declares_and_enforces_bounds():
    schema = next(
        item
        for item in ToolRegistry().mcp_schemas()
        if item["name"] == "small_case_enumeration"
    )
    values_schema = schema["inputSchema"]["properties"]["values"]
    assert values_schema["minItems"] == 1
    assert values_schema["maxItems"] == 128
    assert ToolRegistry().validate_arguments(
        "small_case_enumeration",
        {
            "expression": "n-n",
            "variable": "n",
            "values": [],
            "expected": "0",
        },
    )
    assert ToolExecutor().execute(
        "small_case_enumeration",
        {
            "expression": "n-n",
            "variable": "n",
            "values": list(range(129)),
            "expected": "0",
        },
    ).status != "pass"


def test_symbolic_equivalence_is_conservative_about_domain_sensitive_forms():
    executor = ToolExecutor()
    polynomial = executor.execute(
        "symbolic_equivalence",
        {"left": "(x+1)^2", "right": "x^2+2*x+1"},
    )
    removable_singularity = executor.execute(
        "symbolic_equivalence",
        {"left": "(x^2-1)/(x-1)", "right": "x+1", "domains": {"x": "R"}},
    )
    logarithm = executor.execute(
        "symbolic_equivalence",
        {"left": "log(x^2)", "right": "2*log(x)", "domains": {"x": "R"}},
    )
    square_root = executor.execute(
        "symbolic_equivalence",
        {"left": "sqrt(x^2)", "right": "x", "domains": {"x": "R"}},
    )
    fractional_power = executor.execute(
        "symbolic_equivalence",
        {"left": "x^(1/2)", "right": "sqrt(x)", "domains": {"x": "R"}},
    )

    assert polynomial.status == "pass"
    assert polynomial.strength == "hard"
    for result in (
        removable_singularity,
        logarithm,
        square_root,
        fractional_power,
    ):
        assert not (result.status == "pass" and result.strength == "hard")
        assert result.payload["domain_sensitive"] is True
        if result.status == "unknown":
            assert result.payload["context_complete"] is False


def test_ambiguous_natural_domain_never_yields_unconditional_hard_evidence():
    result = ToolExecutor().execute(
        "symbolic_equivalence",
        {
            "left": "n",
            "right": "n+1",
            "domains": {"n": "N"},
        },
    )

    assert result.status == "unknown"
    assert result.payload["context_complete"] is False
