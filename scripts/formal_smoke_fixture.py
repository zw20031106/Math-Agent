from __future__ import annotations

import json
from typing import Any


_STRICT_CANDIDATE = {
    "method": "direct-deduction",
    "final_answer": "2",
    "public_solution_steps": [
        "Evaluate the sum directly: 1+1=2.",
    ],
    "claims": [
        {
            "claim_id": "c1",
            "statement": "1+1=2",
            "depends_on": [],
            "check_type": "symbolic_equivalence",
            "importance": "critical",
        }
    ],
    "method_steps": [
        {
            "step_id": "s1",
            "kind": "computation",
            "claim_ids": ["c1"],
            "theorem": "",
        }
    ],
    "solution_text": "Adding the two unit quantities gives 1+1=2.",
    "assumptions": [],
    "theorems": [],
    "unresolved_obligations": [],
}


class FormalSmokeClient:
    """Deterministic injected-client fixture for the formal entry contract."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def chat(self, *, messages, temperature, max_tokens) -> str:
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        system = messages[0]["content"]
        user = messages[-1]["content"]
        if system.startswith("You are RouterPlanner"):
            return json.dumps(_router_payload(), ensure_ascii=False)
        if system.startswith("You are LemmaCurator"):
            recipient = json.loads(user)["reply_recipient_role"]
            return json.dumps(
                _agent_envelope(
                    "LemmaArtifact",
                    "complete",
                    result_payload={"lemmas": []},
                    outbound_intents=[{"recipient_role": recipient}],
                    progress_summary="Lemma scan completed.",
                    stop_reason="lemma_scan_complete",
                ),
                ensure_ascii=False,
            )
        if "Public protocol mode is explore" in system or (
            "Public protocol mode is continue" in system
        ):
            return json.dumps(
                _agent_envelope(
                    "ProgressArtifact",
                    "complete",
                    public_state_delta=_progress_delta(),
                    progress_summary="Public exploration completed.",
                    stop_reason="ready_for_candidate",
                ),
                ensure_ascii=False,
            )
        if "AgentTurnPayload 1.0" in system:
            candidate = {
                key: value
                for key, value in _STRICT_CANDIDATE.items()
                if key != "method_steps"
            }
            return json.dumps(
                _agent_envelope(
                    "CandidateArtifact",
                    "publish_candidate",
                    result_payload=candidate,
                    progress_summary="Published a complete candidate.",
                    stop_reason="candidate_complete",
                ),
                ensure_ascii=False,
            )
        return json.dumps(_STRICT_CANDIDATE, ensure_ascii=False)


def _router_payload() -> dict[str, Any]:
    methods = [
        "direct-deduction",
        "structural-transform",
        "constructive-computation",
    ]
    return {
        "primary_subject": "general-math",
        "auxiliary_subject": None,
        "risk_level": "high",
        "method_families": methods,
        "subgoals": [
            {
                "subgoal_id": "sg-1",
                "objective": "Establish the arithmetic result",
                "depends_on": [],
            }
        ],
        "task_proposals": [
            {
                "proposal_id": f"proposal-{index}",
                "agent_role": "PrimarySolver" if index == 1 else "AlternativeSolver",
                "task_type": "solve_primary" if index == 1 else "solve_alternative",
                "subgoal_ids": ["sg-1"],
                "method_family": method,
                "priority": 110 - index * 10,
            }
            for index, method in enumerate(methods, start=1)
        ],
    }


def _progress_delta() -> dict[str, Any]:
    return {
        "public_summary": "Direct arithmetic establishes the result.",
        "strategy": "direct-deduction",
        "subgoals": [],
        "claims": [],
        "open_obligations": [],
        "closed_obligation_ids": [],
        "contradictions": [],
        "next_step": "Synthesize the candidate.",
        "stop_reason": "ready_for_candidate",
    }


def _agent_envelope(
    task_result_type: str,
    action: str,
    *,
    public_state_delta: dict[str, Any] | None = None,
    result_payload: dict[str, Any] | None = None,
    outbound_intents: list[dict[str, Any]] | None = None,
    progress_summary: str,
    stop_reason: str,
) -> dict[str, Any]:
    return {
        "protocol_version": "1.0",
        "task_result_type": task_result_type,
        "action": action,
        "public_state_delta": public_state_delta or {},
        "result_payload": result_payload or {},
        "outbound_intents": outbound_intents or [],
        "progress_summary": progress_summary,
        "stop_reason": stop_reason,
    }


def assert_formal_smoke_result(result: dict[str, Any]) -> None:
    if set(result) != {"id", "status", "final_response", "trace"}:
        raise AssertionError("formal smoke result fields are invalid")
    if result.get("status") != "success":
        raise AssertionError("formal smoke did not reach success")
    if "2" not in str(result.get("final_response", "")):
        raise AssertionError("formal smoke final response does not contain the answer")
    trace = result.get("trace")
    if not isinstance(trace, list):
        raise AssertionError("formal smoke trace is not a list")
    if any(
        isinstance(event, dict)
        and (
            event.get("fallback_used") is True
            or "fallback" in str(event.get("event", "")).lower()
        )
        for event in trace
    ):
        raise AssertionError("formal smoke used fallback")
