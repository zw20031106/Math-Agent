import json

from user_agent import ReasoningAgent

from tests.fake_client import FakeClient


def test_result_is_json_serializable() -> None:
    result = ReasoningAgent(FakeClient()).solve("x^2 = 1", {"idx": 2})
    serialized = json.dumps(result)
    assert serialized
    assert result["final_response"].strip()
