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

    def chat(self, *, messages, temperature, max_tokens):
        del temperature, max_tokens
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
                    }
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
    assert result["trace"][-1]["event"] == "fallback_used"


def test_runtime_accepts_fully_reverified_repair_and_rebuilds_solution_text():
    result = MathForgeHarness(RepairRuntimeClient("B"), _config()).solve(
        "Choose the correct option:\nA. one\nB. two", {}
    )
    repair = next(event for event in result["trace"] if event["event"] == "repair_completed")
    assert repair["rolled_back"] is False
    assert repair["reason"] == "accepted"
    assert "x = x" in result["final_response"]
    assert "STALE BAD DERIVATION" not in result["final_response"]
