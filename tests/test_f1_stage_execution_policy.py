from __future__ import annotations

from mathforge.harness.budget import CallBudget
from mathforge.harness.deadline import DeadlineController
from mathforge.harness.errors import ModelCallRejected
from mathforge.harness.provider import ModelCallGate, OfficialClientProvider


class _RecordingClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def chat(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return "ok"


def test_proof_turn_uses_larger_cap_and_records_effective_policy():
    client = _RecordingClient()
    budget = CallBudget(1)
    budget.consume(stage="primary")
    provider = OfficialClientProvider(client, ModelCallGate(1))

    response = provider.chat(
        messages=[{"role": "user", "content": "prove it"}],
        temperature=0.0,
        max_tokens=65_536,
        budget=budget,
        stage="primary",
        turn_kind="solver_candidate_proof",
        agent_id="PrimarySolver:candidate-1",
    )

    assert response == "ok"
    assert client.calls[0]["max_tokens"] == 12_288
    record = budget.model_call_records[0]
    assert record["turn_kind"] == "solver_candidate_proof"
    assert record["configured_output_tokens"] == 65_536
    assert record["effective_output_tokens"] == 12_288
    assert record["configured_stage_timeout_seconds"] == 270.0
    assert record["effective_stage_timeout_seconds"] <= 270.0
    assert record["finish_reason"] == "unobservable"
    assert record["logical_call_consumed"] is True
    assert record["dispatched"] is True


def test_stage_policy_is_injected_instead_of_hard_coded_by_provider():
    policy = {
        "router": {"max_tokens": 11, "timeout_seconds": 1.0},
        "replan": {"max_tokens": 12, "timeout_seconds": 1.0},
        "solver_progress": {"max_tokens": 13, "timeout_seconds": 1.0},
        "solver_candidate_standard": {
            "max_tokens": 14,
            "timeout_seconds": 1.0,
        },
        "solver_candidate_proof": {
            "max_tokens": 15,
            "timeout_seconds": 1.0,
        },
        "lemma_curator": {"max_tokens": 16, "timeout_seconds": 1.0},
        "peer_review": {"max_tokens": 17, "timeout_seconds": 1.0},
        "verifier": {"max_tokens": 18, "timeout_seconds": 1.0},
        "repair": {"max_tokens": 19, "timeout_seconds": 1.0},
        "finalizer": {"max_tokens": 20, "timeout_seconds": 1.0},
    }
    for spec in policy.values():
        spec["minimum_start_window_seconds"] = 0.5
    client = _RecordingClient()
    provider = OfficialClientProvider(
        client,
        ModelCallGate(1),
        stage_execution_policy=policy,
    )
    assert provider.chat(
        messages=[{"role": "user", "content": "route"}],
        temperature=0.0,
        max_tokens=100,
        turn_kind="router",
    ) == "ok"
    assert client.calls[0]["max_tokens"] == 11


def test_proof_turn_is_not_dispatched_below_its_safe_start_window():
    now = [0.0]
    deadline = DeadlineController(
        soft_deadline_seconds=400.0,
        exploration_deadline_seconds=400.0,
        hard_deadline_seconds=400.0,
        deterministic_finalize_reserve_seconds=50.0,
        model_call_start_margin_seconds=0.0,
        clock=lambda: now[0],
    )
    now[0] = 180.0
    client = _RecordingClient()
    provider = OfficialClientProvider(client, ModelCallGate(1))

    try:
        provider.chat(
            messages=[{"role": "user", "content": "prove it"}],
            temperature=0.0,
            max_tokens=65_536,
            deadline=deadline,
            turn_kind="solver_candidate_proof",
        )
    except ModelCallRejected as error:
        assert error.code == "model_stage_window_insufficient"
    else:
        raise AssertionError("proof turn should not have been dispatched")
    assert client.calls == []
