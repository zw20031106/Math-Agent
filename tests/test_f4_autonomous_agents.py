from __future__ import annotations

import json
import re

import pytest

from mathforge.agent_runtime.autonomy import AgentProgressTracker
from mathforge.agent_runtime.protocol import (
    AgentTurnPayloadParser,
)
from mathforge.config import HarnessConfig
from mathforge.runtime import MathForgeHarness


def _config(**overrides) -> HarnessConfig:
    values = {
        "profile": "f4-test",
        "status": "test",
        "primary_max_tokens": 65_536,
        "max_model_calls": 48,
        "model_call_policy": "adaptive_bounded",
        "max_logical_model_calls_per_problem": 48,
        "soft_call_checkpoints": (16, 28, 40),
        "speculative_exploration_cutoff": 40,
        "closure_reserve_calls": 8,
        "enable_router": True,
        "enable_skills": False,
        "enable_alternatives": True,
        "enable_tools": False,
        "enable_evidence": False,
        "enable_proof_obligations": False,
        "enable_verifier": False,
        "enable_memory": False,
        "enable_lemma_loop": False,
        "enable_rag": False,
        "enable_repair": False,
        "enable_finalizer": False,
        "enable_shadow": False,
        "enable_frozen_lemma_store": False,
        "enable_long_horizon": True,
    }
    values.update(overrides)
    return HarnessConfig(**values)


def _router_payload() -> dict:
    methods = [
        "structural-transform",
        "constructive-computation",
        "direct-deduction",
    ]
    tasks = [
        {
            "proposal_id": "proposal-primary",
            "agent_role": "PrimarySolver",
            "task_type": "solve_primary",
            "subgoal_ids": ["sg-1"],
            "method_family": methods[0],
            "priority": 100,
        },
        {
            "proposal_id": "proposal-alternative-1",
            "agent_role": "AlternativeSolver",
            "task_type": "solve_alternative",
            "subgoal_ids": ["sg-1"],
            "method_family": methods[1],
            "priority": 90,
        },
        {
            "proposal_id": "proposal-alternative-2",
            "agent_role": "AlternativeSolver",
            "task_type": "solve_alternative",
            "subgoal_ids": ["sg-1"],
            "method_family": methods[2],
            "priority": 80,
        },
    ]
    return {
        "primary_subject": "general-math",
        "auxiliary_subject": None,
        "risk_level": "high",
        "method_families": methods,
        "subgoals": [
            {
                "subgoal_id": "sg-1",
                "objective": "Establish the decisive mathematical relation",
                "depends_on": [],
            }
        ],
        "task_proposals": tasks,
    }


def _progress_delta(index: int, role: str) -> dict:
    prefix = "p" if role == "PrimarySolver" else "a"
    return {
        "public_summary": f"{role} added public step {index}.",
        "strategy": (
            "structural-transform"
            if role == "PrimarySolver"
            else "constructive-computation"
        ),
        "subgoals": [
            {
                "subgoal_id": "g1",
                "statement": "Derive the exact result independently.",
                "depends_on": [],
                "exit_condition": "A complete candidate can be synthesized.",
                "status": "active",
            }
        ],
        "claims": [
            {
                "claim_id": f"{prefix}-c{index}",
                "statement": f"Public checkable step {index} for {role}.",
                "depends_on": [],
                "subgoal_ids": ["g1"],
                "importance": "supporting",
                "check_type": "reasoning",
            }
        ],
        "open_obligations": [],
        "closed_obligation_ids": [],
        "contradictions": [],
        "next_step": "Continue or synthesize the candidate.",
        "stop_reason": "",
    }


def _progress_envelope(
    index: int,
    role: str,
    *,
    action: str,
    intents: list[dict] | None = None,
) -> str:
    result_type = {
        "abstain": "CheckpointArtifact",
        "request_tool_check": "ToolRequestArtifact",
    }.get(action, "ProgressArtifact")
    return json.dumps(
        {
            "protocol_version": "1.0",
            "task_result_type": result_type,
            "action": action,
            "public_state_delta": (
                {} if action == "abstain" else _progress_delta(index, role)
            ),
            "result_payload": {},
            "outbound_intents": intents or [],
            "progress_summary": f"{role} action {action} at step {index}",
            "stop_reason": (
                "method exhausted"
                if action == "abstain"
                else "ready_for_candidate"
                if action == "complete"
                else ""
            ),
        },
        ensure_ascii=False,
    )


def _candidate_payload(method: str) -> dict:
    return {
        "method": method,
        "final_answer": "4",
        "public_solution_steps": ["$2+2=4$"],
        "claims": [
            {
                "claim_id": "c-final",
                "statement": "$2+2=4$.",
                "depends_on": [],
                "check_type": "reasoning",
                "importance": "critical",
            }
        ],
        "solution_text": "$2+2=4$.",
        "assumptions": [],
        "theorems": [],
        "unresolved_obligations": [],
    }


def _candidate_envelope(method: str) -> str:
    return json.dumps(
        {
            "protocol_version": "1.0",
            "task_result_type": "CandidateArtifact",
            "action": "publish_candidate",
            "public_state_delta": {},
            "result_payload": _candidate_payload(method),
            "outbound_intents": [],
            "progress_summary": "Published a complete candidate.",
            "stop_reason": "candidate_complete",
        }
    )


def _lemma_envelope(recipient_role: str) -> str:
    return json.dumps(
        {
            "protocol_version": "1.0",
            "task_result_type": "LemmaArtifact",
            "action": "complete",
            "public_state_delta": {},
            "result_payload": {
                "lemmas": [
                    {
                        "statement": "The decisive reduction preserves all conditions.",
                        "conditions": ["Use only the stated assumptions."],
                        "dependencies": [],
                        "proof_sketch": "Check the reduction directly.",
                        "target_obligation_ids": ["sg-1"],
                    }
                ]
            },
            "outbound_intents": [{"recipient_role": recipient_role}],
            "progress_summary": "Published one provisional lemma.",
            "stop_reason": "lemma_batch_complete",
        }
    )


class _LengthResponse(str):
    finish_reason = "length"


class AutonomousClient:
    def __init__(
        self,
        *,
        primary_continues: int = 1,
        request_lemma_role: str = "",
        request_tool_role: str = "",
        request_replan_role: str = "",
        abstain_roles: tuple[str, ...] = (),
        fail_candidate_roles: tuple[str, ...] = (),
        truncate_primary_candidate: bool = False,
        reject_proof_tokens: bool = False,
    ) -> None:
        self.primary_continues = primary_continues
        self.request_lemma_role = request_lemma_role
        self.request_tool_role = request_tool_role
        self.request_replan_role = request_replan_role
        self.abstain_roles = set(abstain_roles)
        self.fail_candidate_roles = set(fail_candidate_roles)
        self.truncate_primary_candidate = truncate_primary_candidate
        self.reject_proof_tokens = reject_proof_tokens
        self.progress_counts = {"PrimarySolver": 0, "AlternativeSolver": 0}
        self.lemma_calls = 0
        self.calls: list[dict] = []
        self._truncated = False
        self._proof_rejections: set[str] = set()

    def chat(self, *, messages, temperature, max_tokens) -> str:
        del temperature
        system = messages[0]["content"]
        user = messages[-1]["content"]
        role = next(
            (
                item
                for item in (
                    "RouterPlanner",
                    "LemmaCurator",
                    "PrimarySolver",
                    "AlternativeSolver",
                )
                if system.startswith(f"You are {item}")
            ),
            "unknown",
        )
        self.calls.append(
            {"role": role, "system": system, "user": user, "max_tokens": max_tokens}
        )
        if role == "RouterPlanner":
            return json.dumps(_router_payload())
        if role == "LemmaCurator":
            self.lemma_calls += 1
            recipient = json.loads(user)["reply_recipient_role"]
            return _lemma_envelope(recipient)
        if "Public protocol mode is explore" in system or (
            "Public protocol mode is continue" in system
        ):
            self.progress_counts[role] += 1
            index = self.progress_counts[role]
            if role in self.abstain_roles:
                return _progress_envelope(index, role, action="abstain")
            if self.request_lemma_role == role and index == 1:
                return _progress_envelope(
                    index,
                    role,
                    action="request_lemma",
                    intents=[
                        {
                            "recipient_role": "LemmaCurator",
                            "request": "Prove the decisive reduction.",
                            "target_obligation_ids": ["sg-1"],
                        }
                    ],
                )
            if self.request_tool_role == role and index == 1:
                return _progress_envelope(
                    index,
                    role,
                    action="request_tool_check",
                    intents=[
                        {
                            "recipient_role": "RouterPlanner",
                            "request": "Check the new public claim.",
                            "target_obligation_ids": [],
                        }
                    ],
                )
            if self.request_replan_role == role and index == 1:
                return _progress_envelope(
                    index,
                    role,
                    action="request_replan",
                    intents=[
                        {
                            "recipient_role": "RouterPlanner",
                            "request": "Replan around the blocked method.",
                            "target_obligation_ids": ["sg-1"],
                        }
                    ],
                )
            limit = self.primary_continues if role == "PrimarySolver" else 0
            action = "continue_reasoning" if index <= limit else "complete"
            return _progress_envelope(index, role, action=action)
        method_match = re.search(
            r"Required core method family: ([a-z-]+)\.",
            user,
        )
        method = method_match.group(1) if method_match else "direct-deduction"
        if role in self.fail_candidate_roles:
            return "{}"
        if (
            self.reject_proof_tokens
            and max_tokens == 12_288
            and role not in self._proof_rejections
        ):
            self._proof_rejections.add(role)
            raise RuntimeError("provider rejects 12288 output tokens")
        response = _candidate_envelope(method)
        if (
            self.truncate_primary_candidate
            and role == "PrimarySolver"
            and not self._truncated
        ):
            self._truncated = True
            return _LengthResponse(response)
        return response


def _event(result: dict, name: str) -> dict:
    return next(item for item in result["trace"] if item["event"] == name)


def test_agent_turn_parser_rejects_host_owned_ids():
    payload = json.loads(
        _progress_envelope(1, "PrimarySolver", action="continue_reasoning")
    )
    payload["public_state_delta"]["agent_id"] = "forged"
    with pytest.raises(ValueError, match="Host-owned"):
        AgentTurnPayloadParser().parse(json.dumps(payload))


def test_stall_detector_allows_ten_real_deltas_and_stops_repeated_hash():
    tracker = AgentProgressTracker()
    last = None
    for index in range(1, 11):
        parsed = AgentTurnPayloadParser().parse(
            _progress_envelope(
                index,
                "PrimarySolver",
                action="continue_reasoning",
            )
        )
        last = tracker.observe("primary", parsed.payload)
        assert last.continue_allowed
        assert last.information_gain > 0
    repeated = tracker.observe("primary", parsed.payload)
    assert not repeated.continue_allowed
    assert repeated.stop_reason == "repeated_public_artifact_hash"


def test_autonomous_solver_runs_beyond_six_turns_and_has_no_planned_rounds():
    client = AutonomousClient(primary_continues=10)
    result = MathForgeHarness(client, _config()).solve("Compute 2+2.", {})
    planned = _event(result, "autonomous_solver_planned")
    completed = _event(result, "reasoning_loop_completed")
    records = _event(result, "budget_summary")["model_call_records"]

    assert "fixed_planned_rounds" not in planned
    assert "planned_rounds" not in completed
    assert completed["progress_turns"] >= 12
    assert completed["candidate_attempts"] == 2
    assert client.progress_counts["PrimarySolver"] == 11
    assert client.lemma_calls >= 1
    assert records[0]["agent_role"] == "RouterPlanner"
    lemma_index = next(
        index
        for index, record in enumerate(records)
        if record["agent_role"] == "LemmaCurator"
    )
    assert lemma_index > 2
    assert {
        item["agent_role"] for item in records if item["stage"] in {"primary", "alternative"}
    } == {"PrimarySolver", "AlternativeSolver"}
    assert all(
        item["effective_output_tokens"] == 4096
        for item in records
        if item["turn_kind"] == "solver_progress"
    )
    assert result["final_response"].strip()


def test_lemma_request_reply_messages_wake_solver_and_remain_unverified():
    client = AutonomousClient(request_lemma_role="AlternativeSolver")
    result = MathForgeHarness(client, _config()).solve("Compute 2+2.", {})
    protocol = _event(result, "agent_protocol")
    message_types = [item["message_type"] for item in protocol["messages"]]
    lemma_events = [
        item for item in result["trace"] if item["event"] == "lemma_request_completed"
    ]

    assert "lemma_requested" in message_types
    assert message_types.count("lemma_published") >= 3
    assert lemma_events[-1]["requester_role"] == "AlternativeSolver"
    assert lemma_events[-1]["solver_woken"] is True
    assert lemma_events[-1]["hard_fact_eligible"] is False


def test_tool_and_replan_requests_publish_messages_and_wake_requester():
    tool_client = AutonomousClient(request_tool_role="PrimarySolver")
    tool_result = MathForgeHarness(tool_client, _config()).solve(
        "Compute 2+2.",
        {},
    )
    tool_protocol = _event(tool_result, "agent_protocol")
    tool_event = _event(tool_result, "agent_tool_request_completed")
    assert "tool_check_requested" in {
        item["message_type"] for item in tool_protocol["messages"]
    }
    assert tool_event["solver_woken"] is True
    assert tool_event["status"] == "unavailable"

    replan_client = AutonomousClient(request_replan_role="AlternativeSolver")
    replan_result = MathForgeHarness(replan_client, _config()).solve(
        "Compute 2+2.",
        {},
    )
    replan_protocol = _event(replan_result, "agent_protocol")
    replan_event = _event(replan_result, "agent_replan_completed")
    message_types = {
        item["message_type"] for item in replan_protocol["messages"]
    }
    assert "replan_requested" in message_types
    assert replan_event["solver_woken"] is True
    assert replan_event["plan_version"] == 2


def test_solver_isolation_and_alternative_failure_do_not_pollute_primary():
    client = AutonomousClient(
        primary_continues=1,
        fail_candidate_roles=("AlternativeSolver",),
    )
    result = MathForgeHarness(client, _config()).solve("Compute 2+2.", {})
    primary_prompts = [
        item["user"] for item in client.calls if item["role"] == "PrimarySolver"
    ]
    alternative_prompts = [
        item["user"]
        for item in client.calls
        if item["role"] == "AlternativeSolver"
    ]
    fanout = _event(result, "candidate_fanout_completed")

    assert "alternative-1" in fanout["failed"]
    assert "primary-1" in fanout["completed"]
    assert all("a-c1" not in prompt for prompt in primary_prompts)
    assert all("p-c1" not in prompt for prompt in alternative_prompts)
    assert result["final_response"].strip()


def test_both_solver_agents_may_abstain_without_invalid_public_output():
    client = AutonomousClient(
        abstain_roles=("PrimarySolver", "AlternativeSolver")
    )
    result = MathForgeHarness(client, _config()).solve("Compute 2+2.", {})

    assert result["final_response"].strip()
    assert result["run_metrics"]["outcome"] == "fallback"
    assert client.progress_counts == {
        "PrimarySolver": 1,
        "AlternativeSolver": 1,
    }
    assert [item["role"] for item in client.calls[:3]] == [
        "RouterPlanner",
        "PrimarySolver",
        "AlternativeSolver",
    ]
    assert all(
        item["role"] in {"PrimarySolver", "AlternativeSolver"}
        for item in client.calls[3:]
    )
    assert not any(item["role"] == "LemmaCurator" for item in client.calls)
    recovery_starts = [
        item
        for item in result["trace"]
        if item["event"] == "candidate_generation_started"
        and (item.get("replacement") or item.get("emergency"))
    ]
    assert len(recovery_starts) == 3


def test_length_candidate_with_complete_payload_is_salvaged_without_recall():
    client = AutonomousClient(truncate_primary_candidate=True)
    result = MathForgeHarness(client, _config()).solve("Compute 2+2.", {})
    protocol = _event(result, "agent_protocol")
    partial = [
        item
        for item in protocol["artifacts"]
        if item["artifact_type"] == "CandidateArtifact"
        and item["payload"]["host_completion"]["status"] == "partial"
    ]
    records = _event(result, "budget_summary")["model_call_records"]

    assert partial
    assert not any(
        item["event"] == "candidate_partial_recovery_started"
        for item in result["trace"]
    )
    assert not any(
        item["turn_kind"] == "solver_compact_synthesis" for item in records
    )
    assert any(
        item["protocol_parse_tier"] == "strict_json"
        and item["finish_reason"] == "length"
        for item in records
        if item["turn_kind"] == "solver_candidate_standard"
    )
    assert all(
        "Published a complete candidate." not in item["user"]
        for item in client.calls
        if "compact_synthesis recovery" in item["system"]
    )
    assert result["final_response"].strip()


def test_simple_candidate_turns_use_2048_tokens():
    result = MathForgeHarness(AutonomousClient(), _config()).solve(
        "Compute 2+2.",
        {},
    )
    records = _event(result, "budget_summary")["model_call_records"]
    standard = [
        item for item in records if item["turn_kind"] == "solver_candidate_standard"
    ]
    assert len(standard) == 2
    assert all(item["effective_output_tokens"] == 2048 for item in standard)


def test_proof_turns_use_8192_without_oversized_canary_degradation():
    client = AutonomousClient(reject_proof_tokens=True)
    result = MathForgeHarness(client, _config()).solve(
        "Prove that 2+2=4.",
        {"response_mode": "proof_full"},
    )
    degradations = [
        item
        for item in result["trace"]
        if item["event"] == "proof_token_canary_degraded"
    ]
    records = _event(result, "budget_summary")["model_call_records"]

    assert degradations == []
    assert any(
        item["turn_kind"] == "solver_candidate_proof"
        and item["effective_output_tokens"] == 8192
        for item in records
    )
    assert result["final_response"].strip()
