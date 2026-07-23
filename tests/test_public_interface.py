import pytest

from mathforge.output.public_result import build_public_result
from user_agent import ReasoningAgent

from tests.fake_client import FakeClient


def test_public_interface_returns_required_contract() -> None:
    result = ReasoningAgent(client=FakeClient()).solve("1 + 1", {"idx": 1})
    assert set(result) == {"id", "final_response", "trace"}
    assert result["id"] == 1
    assert result["final_response"] == "Solved independently: 1 + 1"
    assert isinstance(result["trace"], list)


def test_constructor_tolerates_runner_extras() -> None:
    agent = ReasoningAgent(FakeClient(), "ignored", legacy=True)
    assert agent.solve("x", {})["final_response"]


def test_public_output_rejects_empty_response_and_non_list_trace() -> None:
    with pytest.raises(ValueError, match="non-empty final_response"):
        build_public_result(1, {"final_response": "", "trace": []})
    with pytest.raises(ValueError, match="list-valued trace"):
        build_public_result(1, {"final_response": "answer", "trace": {}})
