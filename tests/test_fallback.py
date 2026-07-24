from user_agent import ReasoningAgent

from tests.fake_client import FakeClient


def test_provider_failure_returns_non_empty_fallback() -> None:
    result = ReasoningAgent(FakeClient(fail=True)).solve("hard problem", {})
    assert result["final_response"].strip()
    assert result["trace"][-1]["event"] == "run_completed"
    assert result["trace"][-1]["outcome"] == "fallback"
    assert result["trace"][-1]["error_code"] == "all_candidates_failed"
    assert result["trace"][-1]["final_phase"] == "fallback_completed"
    fallback = next(event for event in result["trace"] if event["event"] == "fallback_used")
    assert fallback["reason"] == "all_candidates_failed"
    assert fallback["failed_phase"] == "context_ready"


def test_empty_problem_still_returns_non_empty_fallback() -> None:
    result = ReasoningAgent(FakeClient(fail=True)).solve("", {})
    assert result["final_response"] == "No mathematical problem was provided."
