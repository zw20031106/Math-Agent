from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


PROTOCOL_SCHEMA_VERSION = "1.0"

ARTIFACT_TYPES = frozenset(
    {
        "ProblemArtifact",
        "RouteArtifact",
        "PlanArtifact",
        "ProgressArtifact",
        "LemmaArtifact",
        "CandidateArtifact",
        "ToolRequestArtifact",
        "EvidenceArtifact",
        "ObligationArtifact",
        "PeerReviewArtifact",
        "RebuttalArtifact",
        "ConflictGraphArtifact",
        "CritiqueArtifact",
        "RepairPatchArtifact",
        "RepairResultArtifact",
        "AuditArtifact",
        "DecisionArtifact",
        "CheckpointArtifact",
    }
)

MESSAGE_TYPES = frozenset(
    {
        "plan_published",
        "task_assignment_proposed",
        "progress_shared",
        "lemma_requested",
        "lemma_published",
        "evidence_available",
        "candidate_published",
        "peer_review_requested",
        "peer_review_published",
        "rebuttal_published",
        "conflict_escalated",
        "replan_requested",
        "repair_requested",
        "repair_published",
        "audit_requested",
        "audit_published",
        "task_abstained",
        "task_failed",
        "conversation_closed",
    }
)

ACTION_TYPES = frozenset(
    {
        "continue_reasoning",
        "publish_candidate",
        "request_tool_check",
        "request_lemma",
        "send_message",
        "request_peer_review",
        "challenge_candidate",
        "publish_rebuttal",
        "request_replan",
        "request_repair",
        "abstain",
        "complete",
    }
)

TASK_TYPES = frozenset(
    {
        "route_and_plan",
        "replan",
        "solve_primary",
        "solve_alternative",
        "continue_reasoning",
        "curate_lemmas",
        "answer_lemma_request",
        "peer_review_candidate",
        "respond_to_peer_review",
        "cross_exam_candidates",
        "repair_claims",
        "solve_new_branch",
        "final_audit",
        "copy_finalize",
    }
)


@dataclass(frozen=True)
class AgentTurnPayload:
    protocol_version: str
    task_result_type: str
    action: str
    public_state_delta: dict[str, Any]
    result_payload: dict[str, Any]
    outbound_intents: tuple[dict[str, Any], ...]
    progress_summary: str
    stop_reason: str

    def __post_init__(self) -> None:
        if self.protocol_version != PROTOCOL_SCHEMA_VERSION:
            raise ValueError("invalid AgentTurnPayload protocol version")
        if self.action not in ACTION_TYPES:
            raise ValueError("invalid AgentTurnPayload action")
        if not self.task_result_type or not self.progress_summary:
            raise ValueError("AgentTurnPayload public fields must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "task_result_type": self.task_result_type,
            "action": self.action,
            "public_state_delta": deepcopy(self.public_state_delta),
            "result_payload": deepcopy(self.result_payload),
            "outbound_intents": [deepcopy(item) for item in self.outbound_intents],
            "progress_summary": self.progress_summary,
            "stop_reason": self.stop_reason,
        }


@dataclass(frozen=True)
class TurnContext:
    agent_id: str
    role: str
    mode: str
    task_id: str
    task_type: str
    turn_id: str
    turn_kind: str
    artifact_type: str
    message_type: str
    recipient_role: str
    plan_id: str = ""
    subgoal_ids: tuple[str, ...] = ()
    method_family: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "mode": self.mode,
            "task_id": self.task_id,
            "task_type": self.task_type,
            "turn_id": self.turn_id,
            "turn_kind": self.turn_kind,
            "artifact_type": self.artifact_type,
            "message_type": self.message_type,
            "recipient_role": self.recipient_role,
            "plan_id": self.plan_id,
            "subgoal_ids": list(self.subgoal_ids),
            "method_family": self.method_family,
        }


@dataclass(frozen=True)
class TurnLineage:
    agent_id: str
    task_id: str
    turn_id: str
    artifact_id: str = ""
    message_id: str = ""
    status: str = "started"
    failure_code: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "agent_id": self.agent_id,
            "task_id": self.task_id,
            "turn_id": self.turn_id,
            "artifact_id": self.artifact_id,
            "message_id": self.message_id,
            "status": self.status,
            "failure_code": self.failure_code,
        }
