from __future__ import annotations

import json

from mathforge.config import HarnessConfig
from mathforge.runtime import MathForgeHarness


def _config() -> HarnessConfig:
    return HarnessConfig(
        max_model_calls=2,
        model_max_concurrency=1,
        enable_router=False,
        enable_skills=False,
        enable_alternatives=False,
        enable_tools=True,
        enable_evidence=True,
        enable_proof_obligations=False,
        enable_verifier=False,
        enable_memory=False,
        enable_lemma_loop=False,
        enable_rag=False,
        enable_repair=True,
        enable_finalizer=False,
    )


class RepairRuntimeClient:
    def __init__(self, repaired_answer: str) -> None:
        self.repaired_answer = repaired_answer
        self.calls = []

    def chat(self, *, messages, temperature, max_tokens):
        del temperature, max_tokens
        self.calls.append(messages)
        if messages[0]["content"].startswith("You are RepairAgent"):
            return json.dumps(
                {
                    "final_answer": self.repaired_answer,
                    "claims": [
                        {
                            "claim_id": "failed",
                            "statement": "x = x",
                            "check_type": "symbolic_equivalence",
                        }
                    ],
                }
            )
        return json.dumps(
            {
                "method": "bad",
                "solution_text": "STALE BAD DERIVATION",
                "final_answer": "A",
                "answer_type": "choice",
                "claims": [
                    {
                        "claim_id": "failed",
                        "statement": "x = x+1",
                        "check_type": "symbolic_equivalence",
                    },
                    {
                        "claim_id": "safe",
                        "statement": "UNRELATED_SAFE_CLAIM",
                        "check_type": "reasoning",
                    },
                ],
            }
        )


def test_runtime_rechecks_repaired_answer_type_and_rolls_back_invalid_patch():
    result = MathForgeHarness(RepairRuntimeClient("not-a-choice"), _config()).solve(
        "Choose the correct option:\nA. one\nB. two", {}
    )
    repair = next(event for event in result["trace"] if event["event"] == "repair_completed")
    assert repair["rolled_back"] is True
    assert repair["reason"] == "candidate_validation_failed"
    assert result["trace"][-1]["event"] == "run_completed"
    assert any(event["event"] == "fallback_used" for event in result["trace"])


def test_runtime_accepts_fully_reverified_repair_and_rebuilds_solution_text():
    client = RepairRuntimeClient("B")
    result = MathForgeHarness(client, _config()).solve(
        "Choose the correct option:\nA. one\nB. two", {}
    )
    repair = next(event for event in result["trace"] if event["event"] == "repair_completed")
    assert repair["rolled_back"] is False
    assert repair["reason"] == "accepted"
    rebalanced = next(
        event
        for event in result["trace"]
        if event["event"] == "call_allocation_rebalanced"
    )
    assert rebalanced["evidence_repair_triggers"] == {
        "primary-1": ["failed"]
    }
    assert rebalanced["repair_reserve"] == 1
    final_states = next(
        event
        for event in result["trace"]
        if event["event"] == "candidate_final_states"
    )
    assert any(
        state["candidate_id"] == "primary-1-v2"
        and state["status"] == "selected"
        for state in final_states["candidates"]
    )
    assert "x = x" in result["final_response"]
    assert "STALE BAD DERIVATION" not in result["final_response"]
    repair_prompt = next(
        messages[-1]["content"]
        for messages in client.calls
        if messages[0]["content"].startswith("You are RepairAgent")
    )
    assert "context_snapshot_id" in repair_prompt
    assert "UNRELATED_SAFE_CLAIM" not in repair_prompt
