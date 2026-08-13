from user_agent import ReasoningAgent

from tests.fake_client import FakeClient


def test_provider_failure_returns_non_empty_fallback() -> None:
    result = ReasoningAgent(FakeClient(fail=True)).solve("hard problem", {})
    assert result["final_response"].strip()
    assert result["trace"][-1]["step"] == "finalize"
    assert "outcome: fallback" in result["trace"][-1]["content"]


def test_empty_problem_still_returns_non_empty_fallback() -> None:
    result = ReasoningAgent(FakeClient(fail=True)).solve("", {})
    assert result["final_response"] == r"\boxed{0}"
