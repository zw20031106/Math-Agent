from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from mathforge.agent_runtime.artifact_store import SessionArtifactStore, stable_payload_hash
from mathforge.agent_runtime.definitions import AgentRegistry
from mathforge.agent_runtime.mailbox import SessionMailbox
from mathforge.agent_runtime.runtime import SessionAgentRuntime
from mathforge.agent_runtime.state import AgentInstance, AgentStateRegistry, AgentTaskRegistry
from mathforge.runtime import MathForgeHarness
from tests.test_phase2_concurrency_lifecycle import FakeClient, _minimal_config


def _services(session_id: str = "a" * 32):
    definitions = AgentRegistry.default()
    agents = AgentStateRegistry(session_id, definitions)
    primary = AgentInstance(f"{session_id}:PrimarySolver:solve:1", session_id, "PrimarySolver", "solve", "primary")
    verifier = AgentInstance(f"{session_id}:VerifierSkeptic:cross_exam:1", session_id, "VerifierSkeptic", "cross_exam", "verifier")
    agents.create(primary)
    agents.create(verifier)
    tasks = AgentTaskRegistry(session_id, agents, definitions)
    task = tasks.create("solve_primary", primary.agent_id)
    artifacts = SessionArtifactStore(session_id, agents, definitions)
    mailbox = SessionMailbox(session_id, agents, tasks, artifacts, definitions)
    return definitions, agents, primary, verifier, tasks, task, artifacts, mailbox


def test_artifacts_are_immutable_stably_hashed_and_parent_checked():
    _, _, primary, _, _, task, store, _ = _services()
    payload = {"answer": [2, 1], "meta": {"b": 2, "a": 1}}
    first = store.publish(artifact_type="CandidateArtifact", producer_agent_id=primary.agent_id, task_id=task.task_id, turn_id="turn-1", payload=payload)
    payload["answer"].append(3)
    restored = store.get(first.artifact_id)
    assert restored.payload == {"answer": [2, 1], "meta": {"b": 2, "a": 1}}
    restored.payload["answer"].append(9)
    assert store.get(first.artifact_id).payload["answer"] == [2, 1]
    assert first.payload_sha256 == stable_payload_hash({"meta": {"a": 1, "b": 2}, "answer": [2, 1]})
    with pytest.raises(ValueError, match="parent artifact"):
        store.publish(artifact_type="CandidateArtifact", producer_agent_id=primary.agent_id, task_id=task.task_id, turn_id="turn-2", payload={}, parent_artifact_ids=("foreign",))


def test_cross_session_and_agent_write_acl_are_enforced():
    definitions, agents, primary, verifier, _, task, store, _ = _services()
    with pytest.raises(PermissionError, match="cannot write"):
        store.publish(artifact_type="CandidateArtifact", producer_agent_id=verifier.agent_id, task_id=task.task_id, turn_id="turn-1", payload={})
    foreign = AgentInstance("foreign:PrimarySolver:solve:1", "foreign", "PrimarySolver", "solve", "foreign")
    with pytest.raises(ValueError, match="cross-session"):
        agents.create(foreign)
    assert definitions.get("PrimarySolver").role == primary.role


def test_mailbox_deduplicates_validates_replies_and_closes_threads():
    _, _, primary, verifier, _, task, store, mailbox = _services()
    first_artifact = store.publish(artifact_type="CandidateArtifact", producer_agent_id=primary.agent_id, task_id=task.task_id, turn_id="turn-1", payload={"v": 1})
    thread = mailbox.create_thread((primary.agent_id, verifier.agent_id))
    kwargs = dict(thread_id=thread.thread_id, sender_agent_id=primary.agent_id, recipient_agent_id=verifier.agent_id, task_id=task.task_id, message_type="candidate_published", artifact_ids=(first_artifact.artifact_id,), public_summary="candidate ready")
    first = mailbox.send(**kwargs)
    assert mailbox.send(**kwargs).message_id == first.message_id
    second_artifact = store.publish(artifact_type="CandidateArtifact", producer_agent_id=primary.agent_id, task_id=task.task_id, turn_id="turn-2", payload={"v": 2}, parent_artifact_ids=(first_artifact.artifact_id,))
    with pytest.raises(ValueError, match="reply_to"):
        mailbox.send(**{**kwargs, "artifact_ids": (second_artifact.artifact_id,), "public_summary": "revision"})
    with pytest.raises(ValueError, match="invalid"):
        mailbox.send(**{**kwargs, "artifact_ids": (second_artifact.artifact_id,), "public_summary": "revision", "reply_to_message_id": "missing"})
    mailbox.send(**{**kwargs, "artifact_ids": (second_artifact.artifact_id,), "public_summary": "revision", "reply_to_message_id": first.message_id})
    mailbox.close(thread.thread_id)
    with pytest.raises(RuntimeError, match="closed"):
        mailbox.send(**kwargs)


def test_agent_state_machine_rejects_invalid_transitions():
    definitions = AgentRegistry.default()
    agents = AgentStateRegistry("s", definitions)
    instance = AgentInstance("s:PrimarySolver:solve:1", "s", "PrimarySolver", "solve", "x")
    agents.create(instance)
    with pytest.raises(RuntimeError, match="invalid Agent transition"):
        agents.transition(instance.agent_id, "waiting_message")
    agents.transition(instance.agent_id, "running")
    agents.transition(instance.agent_id, "waiting_message")
    agents.transition(instance.agent_id, "ready")
    agents.transition(instance.agent_id, "completed")


def test_shadow_runtime_produces_causal_artifact_and_message_lineage():
    runtime = SessionAgentRuntime("b" * 32, AgentRegistry.default())
    turn = runtime.begin_model_turn(stage="primary", turn_kind="solver_candidate_standard", agent_hint="PrimarySolver:candidate-1")
    runtime.mark_dispatched(turn.turn_id, budget_snapshot={"used_calls": 1, "max_calls": 24})
    lineage = runtime.complete_model_turn(turn.turn_id, '{"answer":"2"}')
    snapshot = runtime.finalize([{"turn_id": turn.turn_id}])
    artifact_ids = {item["artifact_id"] for item in snapshot["artifacts"]}
    message_ids = {item["message_id"] for item in snapshot["messages"]}
    assert snapshot["call_turn_count_match"] is True
    assert lineage["output_artifact_id"] in artifact_ids
    assert lineage["message_id"] in message_ids
    assert snapshot["messages"][0]["artifact_ids"] == (lineage["output_artifact_id"],)
    runtime.release()
    assert runtime.released is True
    assert runtime.agents.snapshot() == []


def test_three_concurrent_solves_have_no_agent_protocol_crossover(monkeypatch):
    captured: list[SessionAgentRuntime] = []

    class RecordingRuntime(SessionAgentRuntime):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            captured.append(self)

    monkeypatch.setattr("mathforge.runtime.SessionAgentRuntime", RecordingRuntime)
    harness = MathForgeHarness(FakeClient(delay=0.002), _minimal_config())
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda i: harness.solve(f"Compute {i}+1.", {"idx": i}), range(3)))
    session_ids = {result["run_metrics"]["session_id"] for result in results}
    assert len(session_ids) == 3
    for result in results:
        protocol = next(event for event in result["trace"] if event["event"] == "agent_protocol")
        session_id = result["run_metrics"]["session_id"]
        assert protocol["call_turn_count_match"] is True
        assert all(item["session_id"] == session_id for item in protocol["agents"])
        assert all(item["session_id"] == session_id for item in protocol["artifacts"])
    assert len(captured) == 3
    assert all(runtime.released and runtime.agents.snapshot() == [] for runtime in captured)


def test_every_model_call_has_agent_task_turn_ids_and_success_lineage():
    result = MathForgeHarness(FakeClient(), _minimal_config()).solve(
        "Compute 2+2.",
        {},
    )
    budget = next(
        event for event in result["trace"] if event["event"] == "budget_summary"
    )
    records = budget["model_call_records"]
    assert records
    for record in records:
        assert record["agent_id"]
        assert record["task_id"]
        assert record["turn_id"]
        if record["status"] == "completed":
            assert record["output_artifact_id"]
            assert record["message_id"]


def test_shadow_protocol_publish_fault_does_not_change_legacy_result(monkeypatch):
    def fail_publish(self, _turn_id, _response):
        raise RuntimeError("shadow-only fault")

    monkeypatch.setattr(SessionAgentRuntime, "complete_model_turn", fail_publish)
    result = MathForgeHarness(FakeClient(), _minimal_config()).solve(
        "Compute 3+1.",
        {},
    )
    assert result["run_metrics"]["outcome"] == "primary"
    budget = next(
        event for event in result["trace"] if event["event"] == "budget_summary"
    )
    assert any(
        record.get("agent_protocol_status") == "shadow_publish_failed"
        for record in budget["model_call_records"]
    )
