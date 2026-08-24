from __future__ import annotations

from threading import BoundedSemaphore

import pytest

from mathforge.config import HarnessConfig
from mathforge.harness.terminalizer import MINIMAL_FALLBACK_RESPONSE
from mathforge.output.public_result import (
    build_public_result,
    serialized_public_result_bytes,
)
from mathforge.parsing.answer_salvage import salvage_any_answer
from mathforge.runtime import MathForgeHarness
from tests.fake_client import FakeClient
from user_agent import ReasoningAgent


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (r'{"final_answer":"\\frac{1}{2}"}', r"\boxed{\frac{1}{2}}"),
        (r'{"final_answer":"7","steps":[', r"\boxed{7}"),
        ("最终答案：42", r"\boxed{42}"),
        ("Answer: x=3", r"\boxed{x=3}"),
        (r"work \boxed{\frac{a}{b}}", r"\boxed{\frac{a}{b}}"),
        (
            r"<think>trial \boxed{1}</think> Final answer: 2",
            r"\boxed{2}",
        ),
        (r"<think>unfinished reasoning; 答案：9", r"\boxed{9}"),
        ("first Answer: 1\nAnswer: 5", r"\boxed{5}"),
    ],
)
def test_answer_salvage_covers_complete_partial_and_think_outputs(
    raw: str,
    expected: str,
) -> None:
    assert salvage_any_answer([raw]) == expected


def test_answer_salvage_prefers_the_latest_response() -> None:
    assert salvage_any_answer(["Answer: 1", "Answer: 8"]) == r"\boxed{8}"


def test_raw_responses_are_available_by_public_case_id() -> None:
    config = HarnessConfig(
        profile="custom",
        status="test",
        max_model_calls=8,
        max_logical_model_calls_per_problem=8,
        soft_call_checkpoints=(4, 6),
        speculative_exploration_cutoff=6,
        closure_reserve_calls=2,
        enable_alternatives=False,
        enable_tools=False,
        enable_evidence=False,
        enable_proof_obligations=False,
        enable_rebuttal=False,
        enable_verifier=False,
        enable_memory=False,
        enable_lemma_loop=False,
        enable_rag=False,
        enable_repair=False,
        enable_finalizer=False,
        enable_long_horizon=False,
        enable_frozen_lemma_store=False,
    )
    harness = MathForgeHarness(FakeClient(), config)

    harness.solve("Compute 2+2.", {"idx": "case-raw"})

    responses = harness.last_raw_responses("case-raw")
    assert responses
    assert all(isinstance(item, str) and item for item in responses)


class _FailingHarness:
    def __init__(self, raw_responses):
        self._raw_responses = list(raw_responses)

    def solve(self, problem, metadata, **kwargs):
        del problem, metadata, kwargs
        raise RuntimeError("simulated terminal failure")

    def last_raw_responses(self, identifier):
        del identifier
        return list(self._raw_responses)

    def release_raw_responses(self, identifier):
        del identifier


def test_user_agent_exception_path_salvages_a_real_answer() -> None:
    agent = ReasoningAgent.__new__(ReasoningAgent)
    agent._harness = _FailingHarness([r'{"final_answer":"11","steps":['])
    agent._case_gate = BoundedSemaphore(1)

    result = agent.solve("hard problem", {"idx": 11})

    assert result["status"] == "failed"
    assert result["final_response"] == "11"


@pytest.mark.parametrize(
    "scenario",
    [
        "empty_response",
        "none_response",
        "empty_trace",
        "non_list_trace",
        "malformed_trace_event",
        "unknown_trace_schema",
        "invalid_status",
        "conflicting_status",
        "timeout",
        "provider_timeout",
        "circuit_open",
        "schema_invalid",
        "truncated_json",
        "think_only",
        "oversized_response",
        "unsafe_trace",
        "non_mapping_result",
        "fallback_outcome",
        "error_outcome",
        "missing_outcome",
    ],
)
def test_twenty_failure_scenarios_always_deliver_a_nonempty_answer(
    scenario: str,
) -> None:
    result = _failure_result(scenario)
    public = build_public_result(scenario, result)

    assert public["final_response"].strip()
    assert "请重新提交" not in public["final_response"]
    assert isinstance(public["trace"], list)
    assert serialized_public_result_bytes(public) <= 4_000_000


def _failure_result(scenario: str):
    base = {
        "final_response": r"\boxed{6}",
        "trace": [{"event": "run_completed", "outcome": "fallback"}],
    }
    if scenario == "empty_response":
        return {**base, "final_response": ""}
    if scenario == "none_response":
        return {**base, "final_response": None}
    if scenario == "empty_trace":
        return {**base, "trace": []}
    if scenario == "non_list_trace":
        return {**base, "trace": {"event": "run_completed"}}
    if scenario == "malformed_trace_event":
        return {**base, "trace": [None, "bad"]}
    if scenario == "unknown_trace_schema":
        return {**base, "trace": [{"schema_version": "999"}]}
    if scenario == "invalid_status":
        return {**base, "status": "unknown"}
    if scenario == "conflicting_status":
        return {**base, "status": "success"}
    if scenario == "timeout":
        return {
            **base,
            "status": "timeout",
            "trace": [{"event": "run_completed", "outcome": "timeout"}],
        }
    if scenario in {"provider_timeout", "circuit_open", "schema_invalid"}:
        return {**base, "run_metrics": {"outcome": "fallback"}}
    if scenario == "truncated_json":
        return {**base, "final_response": r"\boxed{4}" + "x" * 25_000}
    if scenario == "think_only":
        return {**base, "final_response": "<think>unfinished</think>"}
    if scenario == "oversized_response":
        return {**base, "final_response": "proof " * 6_000 + r"\boxed{12}"}
    if scenario == "unsafe_trace":
        return {**base, "trace": [{"raw_response": "private"}]}
    if scenario == "non_mapping_result":
        return None
    if scenario == "fallback_outcome":
        return {**base, "run_metrics": {"outcome": "fallback"}}
    if scenario == "error_outcome":
        return {**base, "run_metrics": {"outcome": "error"}}
    if scenario == "missing_outcome":
        return {"final_response": MINIMAL_FALLBACK_RESPONSE, "trace": []}
    raise AssertionError(f"unknown test scenario: {scenario}")
