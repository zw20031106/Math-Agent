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
    activity = next(
        event for event in result["trace"] if event["event"] == "model_activity"
    )
    summaries = next(
        event
        for event in result["trace"]
        if event["event"] == "candidate_summaries"
    )["candidates"]
    overview = result["trace"][1]

    assert result["trace"][0]["event"] == "solution_process"
    assert overview["event"] == "workflow_overview"
    assert [step["step_index"] for step in overview["steps"]] == list(
        range(1, len(overview["steps"]) + 1)
    )
    assert [step["phase"] for step in overview["steps"]] == [
        "problem_understanding",
        "planning",
        "candidate_generation",
        "verification",
        "arbitration",
        "finalization",
    ]
    assert overview["selected_candidate_id"] == result["trace"][0][
        "candidate_id"
    ]

    assert activity["call_count"] == len(activity["calls"])
    assert [call["call_index"] for call in activity["calls"]] == list(
        range(1, activity["call_count"] + 1)
    )
    assert {call["role"] for call in activity["calls"]} == {
        "PrimarySolver",
        "AlternativeSolver",
    }
    assert all(call["purpose"] for call in activity["calls"])
    assert all(call["candidate_ids"] for call in activity["calls"])

    assert sum(item["selected"] for item in summaries) == 1
    selected = next(item for item in summaries if item["selected"])
    alternative = next(
        item for item in summaries if item["role"] == "AlternativeSolver"
    )
    assert selected["solution_process_ref"] == "trace[0]"
    assert selected["public_solution_steps"] == []
    assert alternative["public_final_answer"] == "3"
    assert "ALTERNATIVE_PUBLIC_STEP" in str(
        alternative["public_solution_steps"]
    )


def test_failed_model_branch_has_attribution_but_no_fabricated_candidate_content():
    result = ReasoningAgent(_FailedAlternativeClient(), config=_config()).solve(
        "Prove carefully that an integer answer exists.",
        {"idx": "failed-alternative"},
    )
    activity = next(
        event for event in result["trace"] if event["event"] == "model_activity"
    )
    summaries = next(
        event
        for event in result["trace"]
        if event["event"] == "candidate_summaries"
    )["candidates"]
    failed_call = next(
        call for call in activity["calls"] if call["role"] == "AlternativeSolver"
    )
    failed_candidate = next(
        item for item in summaries if item["role"] == "AlternativeSolver"
    )

    assert failed_call["status"] == "failed"
    assert failed_call["failure_code"]
    assert failed_call["candidate_ids"] == [failed_candidate["candidate_id"]]
    assert failed_candidate["public_final_answer"] == ""
    assert failed_candidate["public_solution_steps"] == []
    serialized = json.dumps(result, ensure_ascii=False)
    assert "private alternative transport detail" not in serialized
