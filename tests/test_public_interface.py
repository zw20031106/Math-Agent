from user_agent import ReasoningAgent

from tests.fake_client import FakeClient


def test_public_interface_returns_required_contract() -> None:
    result = ReasoningAgent(client=FakeClient()).solve("1 + 1", {"idx": 1})
    assert result["final_response"] == "Solved independently: 1 + 1"
    assert isinstance(result["trace"], list)
    assert result["run_metrics"]["model_calls"] > 0
    assert result["run_metrics"]["estimated_tokens"] > 0


def test_constructor_tolerates_runner_extras() -> None:
    agent = ReasoningAgent(FakeClient(), "ignored", legacy=True)
    assert agent.solve("x", {})["final_response"]
