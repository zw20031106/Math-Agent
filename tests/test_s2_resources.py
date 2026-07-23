from __future__ import annotations

from dataclasses import replace
import json
from time import perf_counter

from mathforge.config import HarnessConfig
from mathforge.runtime import MathForgeHarness


def _minimal_config(**overrides) -> HarnessConfig:
    config = HarnessConfig(
        profile="test",
        status="test",
        max_model_calls=1,
        enable_router=False,
        enable_skills=False,
        enable_alternatives=False,
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
    return replace(config, **overrides)


class ClaimsClient:
    def __init__(self, count: int, check_type: str = "reasoning") -> None:
        self.count = count
        self.check_type = check_type
        self.calls = 0

    def chat(self, *, messages, temperature, max_tokens):
        del messages, temperature, max_tokens
        self.calls += 1
        return json.dumps(
            {
                "method": "direct",
                "solution_text": "bounded candidate",
                "final_answer": "1",
                "claims": [
                    {
                        "claim_id": f"c{index}",
                        "statement": "x = x",
                        "check_type": self.check_type,
                    }
                    for index in range(self.count)
                ],
            }
        )


def test_session_claim_budget_rejects_oversized_candidate_before_tools():
    client = ClaimsClient(9, "symbolic_equivalence")
    started = perf_counter()
    result = MathForgeHarness(
        client,
        _minimal_config(max_claims=8),
    ).solve("x", {})

    assert perf_counter() - started < 1.0
    assert client.calls == 1
    assert result["run_metrics"]["model_calls"] == 1
    fanout = next(
        event
        for event in result["trace"]
        if event["event"] == "candidate_fanout_completed"
    )
    assert fanout["completed"] == []
    assert fanout["failures"][0]["reason"] == "claim_budget_exhausted"
    assert all(event["event"] != "tool_checks" for event in result["trace"])


def test_malicious_claim_count_fails_before_per_claim_processing():
    client = ClaimsClient(5000, "symbolic_equivalence")
    started = perf_counter()
    result = MathForgeHarness(client, _minimal_config()).solve("x", {})

    assert perf_counter() - started < 1.0
    assert client.calls == 1
    assert result["run_metrics"]["model_calls"] == 1
    assert result["trace"][-1]["event"] == "run_completed"
    assert any(event["event"] == "fallback_used" for event in result["trace"])
    assert all(event["event"] != "tool_checks" for event in result["trace"])


def test_tool_budget_stops_claim_checks_at_session_limit():
    client = ClaimsClient(2, "symbolic_equivalence")
    result = MathForgeHarness(
        client,
        _minimal_config(
            enable_tools=True,
            enable_evidence=True,
            max_tool_calls=1,
            max_isolated_tool_calls=1,
        ),
    ).solve("x", {})

    checks = next(event for event in result["trace"] if event["event"] == "tool_checks")
    assert len(checks["checks"]) == 1
    assert result["run_metrics"]["tool_calls"] == 1
    assert result["run_metrics"]["evidence_records"] == 1
