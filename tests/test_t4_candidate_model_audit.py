from __future__ import annotations

import json

from mathforge.config import HarnessConfig
from tests.fake_client import FakeClient
from user_agent import ReasoningAgent


def _config() -> HarnessConfig:
    return HarnessConfig(
        profile="t4-audit",
        status="test",
        max_model_calls=3,
        model_max_concurrency=2,
        enable_router=False,
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
        enable_shadow=False,
        enable_long_horizon=False,
    )


class _TwoCandidateClient(FakeClient):
    def chat(self, *, messages, temperature, max_tokens):
        payload = json.loads(
            super().chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        )
        if messages[0]["content"].startswith("You are AlternativeSolver"):
            payload["final_answer"] = "3"
            payload["solution_text"] = "ALTERNATIVE_PUBLIC_STEP gives $3$."
            payload["public_solution_steps"] = [
                "ALTERNATIVE_PUBLIC_STEP gives $3$."
            ]
            payload["claims"][0]["statement"] = "The alternative result is $3$."
        return json.dumps(payload, ensure_ascii=False)


class _FailedAlternativeClient(FakeClient):
    def chat(self, *, messages, temperature, max_tokens):
        if messages[0]["content"].startswith("You are AlternativeSolver"):
            raise RuntimeError("private alternative transport detail")
        return super().chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )


def test_model_activity_and_all_generated_candidates_are_publicly_auditable():
    result = ReasoningAgent(_TwoCandidateClient(), config=_config()).solve(
        "Prove carefully that an integer answer exists.",
        {"idx": "two-candidates"},
    )
    activity = next(item for item in result["trace"] if item["step"] == "model_call")
    candidates = next(
        item for item in result["trace"] if item["step"] == "candidate_generation"
    )

    assert result["trace"][0]["step"] == "plan"
    assert result["trace"][-1]["step"] == "finalize"
    assert "PrimarySolver" in activity["content"]
    assert "AlternativeSolver" in activity["content"]
    assert "answer 3" in candidates["content"]


def test_failed_model_branch_has_attribution_but_no_fabricated_candidate_content():
    result = ReasoningAgent(_FailedAlternativeClient(), config=_config()).solve(
        "Prove carefully that an integer answer exists.",
        {"idx": "failed-alternative"},
    )
    activity = next(item for item in result["trace"] if item["step"] == "model_call")
    candidates = next(
        item for item in result["trace"] if item["step"] == "candidate_generation"
    )

    assert "3 model calls" in activity["content"]
    assert "1 successful" in activity["content"]
    assert "1 remained viable" in candidates["content"]
    serialized = json.dumps(result, ensure_ascii=False)
    assert "private alternative transport detail" not in serialized
