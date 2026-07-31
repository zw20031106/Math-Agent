from __future__ import annotations

import json
import re

from mathforge.config import HarnessConfig
from mathforge.runtime import MathForgeHarness
from mathforge.output.public_result import build_public_result


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


def _candidate_payload(
    final_answer: str,
    solution_text: str,
    claims: list[dict],
    *,
    method: str,
) -> dict:
    normalized_claims = [
        {
            **claim,
            "depends_on": list(claim.get("depends_on", [])),
            "importance": claim.get("importance", "critical"),
        }
        for claim in claims
    ]
    return {
        "method": method,
        "method_steps": [
            {
                "step_id": "s1",
                "kind": "conclusion",
                "claim_ids": [normalized_claims[0]["claim_id"]],
                "theorem": "",
            }
        ],
        "solution_text": solution_text,
        "public_solution_steps": [solution_text],
        "final_answer": final_answer,
        "assumptions": [],
        "theorems": [],
        "claims": normalized_claims,
        "unresolved_obligations": [],
    }


class RepairRuntimeClient:
    def __init__(self, repaired_answer: str) -> None:
        self.repaired_answer = repaired_answer
        self.calls = []
        self.primary_method = "direct-deduction"

    def chat(self, *, messages, temperature, max_tokens):
        del temperature, max_tokens
        self.calls.append(messages)
        if messages[0]["content"].startswith("You are RepairAgent"):
            return json.dumps(
                _candidate_payload(
                    self.repaired_answer,
                    "x = x",
                    [
                        {
                            "claim_id": "failed",
                            "statement": "x = x",
                            "check_type": "symbolic_equivalence",
                        }
                    ],
                    method=self.primary_method,
                )
            )
        match = re.search(
            r"Required core method family: ([a-z-]+)\.",
            messages[-1]["content"],
        )
        if match is not None:
            self.primary_method = match.group(1)
        return json.dumps(
            _candidate_payload(
                "A",
                "STALE BAD DERIVATION",
                [
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
                method=self.primary_method,
            )
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
    assert result["final_response"] == r"Final answer: $\mathrm{B}$"
    proposal = next(
        event
        for event in result["trace"]
        if event["event"] == "repair_proposed"
    )
    assert any(
        "x = x" in step
        for step in proposal["proposed_content"]["public_solution_steps"]
    )
    assert "STALE BAD DERIVATION" not in str(proposal["proposed_content"])
    public = build_public_result("repair-audit", result)
    history = next(
        event for event in public["trace"] if event["event"] == "repair_history"
    )
    attempt = history["attempts"][0]
    assert attempt["accepted"] is True
    assert attempt["rolled_back"] is False
    assert attempt["proposed_candidate_id"] == "primary-1-v2"
    assert any("x = x" in str(step) for step in attempt["public_solution_steps"])
    repair_messages = next(
        messages
        for messages in client.calls
        if messages[0]["content"].startswith("You are RepairAgent")
    )
    repair_prompt = repair_messages[-1]["content"]
    assert "context_snapshot_id" in repair_prompt
    assert "Host response mode is answer_only" in repair_messages[0]["content"]
    assert "UNRELATED_SAFE_CLAIM" not in repair_prompt
