from __future__ import annotations

import json
import re
import threading
import time


class FakeClient:
    def __init__(self, *, fail: bool = False, delay: float = 0.0) -> None:
        self.fail = fail
        self.delay = delay
        self.calls: list[dict] = []
        self._lock = threading.Lock()
        self.active_calls = 0
        self.max_active_calls = 0

    def chat(self, *, messages, temperature, max_tokens) -> str:
        with self._lock:
            self.active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self.active_calls)
            self.calls.append(
                {
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
            )
        try:
            if self.delay:
                time.sleep(self.delay)
            if self.fail:
                raise RuntimeError("simulated provider failure")
            system_content = messages[0]["content"]
            user_content = messages[-1]["content"]
            if system_content.startswith("You are RouterPlanner"):
                lowered = user_content.casefold()
                risk_level = (
                    "high"
                    if "prove" in lowered or "contradiction" in lowered
                    else "low"
                    if "equation" in lowered
                    else "medium"
                )
                return json.dumps(
                    _router_payload(risk_level),
                    ensure_ascii=False,
                )
            if system_content.startswith("You are LemmaCurator"):
                recipient = json.loads(user_content)["reply_recipient_role"]
                return json.dumps(
                    _agent_envelope(
                        task_result_type="LemmaArtifact",
                        action="complete",
                        result_payload={"lemmas": []},
                        outbound_intents=[{"recipient_role": recipient}],
                        progress_summary="No additional lemma was needed.",
                        stop_reason="lemma_scan_complete",
                    ),
                    ensure_ascii=False,
                )
            role = (
                "PrimarySolver"
                if system_content.startswith("You are PrimarySolver")
                else "AlternativeSolver"
            )
            if "Public protocol mode is explore" in system_content or (
                "Public protocol mode is continue" in system_content
            ):
                return json.dumps(
                    _agent_envelope(
                        task_result_type="ProgressArtifact",
                        action="complete",
                        public_state_delta=_progress_delta(role),
                        progress_summary=f"{role} completed public exploration.",
                        stop_reason="ready_for_candidate",
                    ),
                    ensure_ascii=False,
                )
            match = re.search(
                r"Problem:\n(.*?)(?:\n\nRequired core method family:|\n\nProvide)",
                user_content,
                re.DOTALL,
            )
            problem = match.group(1) if match else user_content
            method_match = re.search(
                r"Required core method family: ([a-z-]+)\.",
                user_content,
            )
            method = method_match.group(1) if method_match else "direct-deduction"
            candidate = {
                    "method": method,
                    "final_answer": problem,
                    "public_solution_steps": [
                        f"Solved independently: {problem}"
                    ],
                    "claims": [
                        {
                            "claim_id": "c1",
                            "statement": f"The requested result is {problem}.",
                            "depends_on": [],
                            "check_type": "reasoning",
                            "importance": "critical",
                        }
                    ],
                    "method_steps": [
                        {
                            "step_id": "s1",
                            "kind": "conclusion",
                            "claim_ids": ["c1"],
                            "theorem": "",
                        }
                    ],
                    "solution_text": f"Solved independently: {problem}",
                    "assumptions": [],
                    "theorems": [],
                    "unresolved_obligations": [],
                }
            if "AgentTurnPayload 1.0" in system_content:
                candidate.pop("method_steps", None)
                return json.dumps(
                    _agent_envelope(
                        task_result_type="CandidateArtifact",
                        action="publish_candidate",
                        result_payload=candidate,
                        progress_summary="Published a complete candidate.",
                        stop_reason="candidate_complete",
                    ),
                    ensure_ascii=False,
                )
            return json.dumps(candidate, ensure_ascii=False)
        finally:
            with self._lock:
                self.active_calls -= 1


def _router_payload(risk_level: str) -> dict:
    methods = [
        "direct-deduction",
        "structural-transform",
        "constructive-computation",
    ]
    return {
        "primary_subject": "general-math",
        "auxiliary_subject": None,
        "risk_level": risk_level,
        "method_families": methods,
        "subgoals": [
            {
                "subgoal_id": "sg-1",
                "objective": "Establish the requested result",
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


def _progress_delta(role: str) -> dict:
    return {
        "public_summary": f"{role} established a direct public route.",
        "strategy": "direct-deduction",
        "subgoals": [],
        "claims": [],
        "open_obligations": [],
        "closed_obligation_ids": [],
        "contradictions": [],
        "next_step": "Synthesize a complete candidate.",
        "stop_reason": "ready_for_candidate",
    }


def _agent_envelope(
    *,
    task_result_type: str,
    action: str,
    public_state_delta: dict | None = None,
    result_payload: dict | None = None,
    outbound_intents: list[dict] | None = None,
    progress_summary: str,
    stop_reason: str,
) -> dict:
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
