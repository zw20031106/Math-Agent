import pytest

from mathforge.output.public_result import build_public_result
from user_agent import ReasoningAgent

from tests.fake_client import FakeClient


def test_public_interface_returns_required_contract() -> None:
    result = ReasoningAgent(client=FakeClient()).solve("1 + 1", {"idx": 1})
    assert set(result) == {"id", "status", "final_response", "trace"}
    assert result["id"] == 1
    assert result["status"] == "success"
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


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        ("primary", "success"),
        ("fallback", "failed"),
        ("error", "failed"),
        ("timeout", "timeout"),
    ],
)
def test_public_status_is_derived_from_terminal_outcome(outcome, expected) -> None:
    result = build_public_result(
        1,
        {
            "final_response": "terminal response",
            "trace": [{"event": "run_completed", "outcome": outcome}],
        },
    )

    assert result["status"] == expected


def test_public_status_rejects_conflicting_explicit_value() -> None:
    with pytest.raises(ValueError, match="conflicts"):
        build_public_result(
            1,
            {
                "status": "success",
                "final_response": "fallback",
                "trace": [{"event": "run_completed", "outcome": "fallback"}],
            },
        )


def test_public_trace_keeps_solution_content_and_omits_framework_noise() -> None:
    result = ReasoningAgent(client=FakeClient()).solve("1 + 1", {"idx": 1})
    names = [event["event"] for event in result["trace"]]
    candidate = next(
        event for event in result["trace"] if event["event"] == "candidate_generated"
    )

    assert "phase_transition" not in names
    assert "context_view_built" not in names
    assert candidate["content"]["public_solution_steps"]
    assert candidate["content"]["final_answer"]
    assert result["trace"][-1]["event"] == "run_completed"
    assert build_public_result(result["id"], result) == result
