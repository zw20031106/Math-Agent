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
            if system_content.startswith("You are VerifierSkeptic"):
                verifier_input = json.loads(user_content)
                if "Public protocol mode is final_audit" in system_content:
                    candidate = verifier_input["final_active_candidate"]
                    requirements = verifier_input.get("audit_requirements", {})
                    return json.dumps(
                        _agent_envelope(
                            task_result_type="AuditArtifact",
                            action="complete",
                            result_payload={
                                "candidate_id": candidate["candidate_id"],
                                "candidate_version": candidate["version"],
                                "status": "complete_audited",
                                "open_finding_ids": [],
                                "open_obligation_ids": [],
                                "reviewed_artifact_ids": list(
                                    requirements.get("required_artifact_ids", [])
                                ),
                                "reviewed_finding_ids": list(
                                    requirements.get("required_finding_ids", [])
                                ),
                                "reviewed_obligation_ids": list(
                                    requirements.get("required_obligation_ids", [])
                                ),
                                "requested_action": "retain",
                                "public_rationale": (
                                    "The normalized final Candidate and closure "
                                    "Artifacts contain no open review item."
                                ),
                                "stop_reason": "audit_complete",
                            },
                            progress_summary="Final audit completed.",
                            stop_reason="audit_complete",
                        ),
                        ensure_ascii=False,
                    )
                candidates = verifier_input["candidates"]
                peer_findings = [
                    finding
                    for review in verifier_input["peer_reviews"]
                    for finding in review["finding_items"]
                ]
                return json.dumps(
                    _agent_envelope(
                        task_result_type="CritiqueArtifact",
                        action="challenge_candidate",
                        result_payload={
                            "findings": [
                                {
                                    "finding_id": f"verifier-{index}",
                                    "candidate_id": candidate["candidate_id"],
                                    "claim_id": candidate["claims"][0]["claim_id"],
                                    "obligation_ids": [],
                                    "peer_finding_ids": [
                                        item.get("finding_ref", item["finding_id"])
                                        for item in peer_findings
                                        if item["candidate_id"]
                                        == candidate["candidate_id"]
                                    ],
                                    "status": "pass",
                                    "scope": "local",
                                    "actionability": "retain",
                                    "public_rationale": (
                                        "The public Claim is consistent with the "
                                        "Candidate answer and peer exchange."
                                    ),
                                    "missing_condition": "",
                                    "counterexample_summary": "",
                                }
                                for index, candidate in enumerate(candidates, start=1)
                            ],
                            "peer_review_assessments": [
                                {
                                    "finding_id": item.get(
                                        "finding_ref",
                                        item["finding_id"],
                                    ),
                                    "status": "pass",
                                    "public_rationale": (
                                        "The Peer Finding cites a real public Claim."
                                    ),
                                }
                                for item in peer_findings
                            ],
                            "uncovered_goal_ids": [],
                            "recommended_action": "retain",
                            "stop_reason": "cross_exam_complete",
                        },
                        progress_summary="Cross exam completed.",
                        stop_reason="cross_exam_complete",
                    ),
                    ensure_ascii=False,
                )
            role = (
                "PrimarySolver"
                if system_content.startswith("You are PrimarySolver")
                else "AlternativeSolver"
            )
            if "Public protocol mode is peer_review" in system_content:
                review_input = json.loads(user_content)
                candidate = review_input["candidate"]
                claim_id = candidate["claims"][0]["claim_id"]
                return json.dumps(
                    _agent_envelope(
                        task_result_type="PeerReviewArtifact",
                        action="challenge_candidate",
                        result_payload={
                            "finding_items": [
                                {
                                    "finding_id": f"{role}-f1",
                                    "candidate_id": candidate["candidate_id"],
                                    "claim_id": claim_id,
                                    "method_step_id": "",
                                    "obligation_ids": [],
                                    "status": "pass",
                                    "public_rationale": "The cited public Claim supports the answer.",
                                    "missing_condition": "",
                                    "counterexample_summary": "No counterexample was found.",
                                    "severity": "info",
                                }
                            ],
                            "answer_assessment": "consistent",
                            "method_overlap_assessment": "structurally distinct",
                            "missing_conditions": [],
                            "counterexample_attempts": ["Checked the stated boundary."],
                            "unresolved_obligations": [],
                            "recommended_action": "retain",
                            "stop_reason": "review_complete",
                        },
                        progress_summary=f"{role} published a Claim-linked peer review.",
                        stop_reason="review_complete",
                    ),
                    ensure_ascii=False,
                )
            if "Public protocol mode is respond_to_review" in system_content:
                rebuttal_input = json.loads(user_content)
                review = rebuttal_input["peer_review"]
                claim_id = rebuttal_input["candidate"]["claims"][0]["claim_id"]
                return json.dumps(
                    _agent_envelope(
                        task_result_type="RebuttalArtifact",
                        action="publish_rebuttal",
                        result_payload={
                            "responses": [
                                {
                                    "finding_id": finding["finding_id"],
                                    "response": "The cited Claim is retained as published.",
                                    "action": "defend",
                                    "supporting_claim_ids": [claim_id],
                                    "evidence_refs": [],
                                    "requested_followup": "",
                                }
                                for finding in review["finding_items"]
                            ],
                            "stop_reason": "all_findings_answered",
                        },
                        progress_summary=f"{role} answered every peer Finding.",
                        stop_reason="all_findings_answered",
                    ),
                    ensure_ascii=False,
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
            semantic_step = {
                "statement": (
                    f"The {role} {method} public route establishes {problem}."
                ),
                "claim_kind": "reasoning",
                "depends_on": [],
            }
            profile_match = re.search(
                r"Candidate response mode is ([a-z_]+)", system_content
            )
            profile = profile_match.group(1) if profile_match else "answer_only"
            if profile == "proof_full":
                proof_steps = [semantic_step]
                if role == "AlternativeSolver":
                    proof_steps.append(
                        {
                            **semantic_step,
                            "statement": (
                                f"The {method} construction supplies an independent "
                                "intermediate implication."
                            ),
                            "claim_kind": "necessity",
                            "depends_on": [0],
                        }
                    )
                proof_steps.append(
                    {
                        **semantic_step,
                        "statement": f"Therefore {problem} follows.",
                        "claim_kind": "sufficiency",
                        "depends_on": [len(proof_steps) - 1],
                    }
                )
                candidate = {
                    "final_answer": problem,
                    "method": method,
                    "proof_steps": proof_steps,
                    "open_conditions": [],
                }
            elif profile == "worked_solution":
                candidate = {
                    "final_answer": problem,
                    "method": method,
                    "steps": [semantic_step],
                    "uncertainties": [],
                }
            else:
                candidate = {
                    "final_answer": problem,
                    "check": {
                        "statement": semantic_step["statement"],
                        "claim_kind": "reasoning",
                    },
                }
            if "AgentTurnPayload 1.0" in system_content:
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
