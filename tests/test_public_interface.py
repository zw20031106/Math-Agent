import pytest

from mathforge.output.public_result import build_public_result
from user_agent import ReasoningAgent

from tests.fake_client import FakeClient


def test_public_interface_returns_required_contract() -> None:
    result = ReasoningAgent(client=FakeClient()).solve("1 + 1", {"idx": 1})
    assert set(result) == {"id", "status", "final_response", "trace"}
    assert result["id"] == 1
    assert result["status"] == "success"
    assert result["final_response"] == "1 + 1"
    assert isinstance(result["trace"], list)


def test_constructor_tolerates_runner_extras() -> None:
    agent = ReasoningAgent(FakeClient(), "ignored", legacy=True)
    assert agent.solve("x", {})["final_response"]


def test_public_output_repairs_empty_response_and_non_list_trace() -> None:
    empty = build_public_result(1, {"final_response": "", "trace": []})
    malformed = build_public_result(
        1,
        {"final_response": r"\boxed{3}", "trace": {}},
    )

    assert empty["final_response"] == r"\boxed{0}"
    assert isinstance(empty["trace"], list)
    assert malformed["final_response"] == r"\boxed{3}"
    assert isinstance(malformed["trace"], list)


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        ("primary", "failed"),
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


def test_public_status_conflict_degrades_without_losing_answer() -> None:
    result = build_public_result(
        1,
        {
            "status": "success",
            "final_response": r"\boxed{5}",
            "trace": [{"event": "run_completed", "outcome": "fallback"}],
        },
    )

    assert result["status"] == "failed"
    assert result["final_response"] == r"\boxed{5}"


def test_public_trace_keeps_selected_solution_and_omits_framework_noise() -> None:
    result = ReasoningAgent(client=FakeClient()).solve("1 + 1", {"idx": 1})
    steps = [event["step"] for event in result["trace"]]
    serialized = str(result["trace"])

    assert "phase_transition" not in serialized
    assert "context_view_built" not in serialized
    assert "candidate_generated" not in serialized
    assert steps[0] == "plan"
    assert "reasoning" in steps
    assert steps[-1] == "finalize"
    assert build_public_result(result["id"], result) == result
