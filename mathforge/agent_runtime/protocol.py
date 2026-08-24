from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import re
from typing import Any

from mathforge.parsing.answer_extraction import prepare_model_text
from mathforge.parsing.structured_output import StructuredOutputRecoveryLayer


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
        "tool_check_requested",
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
        if not isinstance(self.public_state_delta, dict):
            raise ValueError("AgentTurnPayload public_state_delta must be an object")
        if not isinstance(self.result_payload, dict):
            raise ValueError("AgentTurnPayload result_payload must be an object")
        if any(not isinstance(item, dict) for item in self.outbound_intents):
            raise ValueError("AgentTurnPayload outbound_intents must contain objects")
        if self.action == "publish_candidate" and not self.result_payload:
            raise ValueError("publish_candidate requires result_payload")
        if self.action == "continue_reasoning" and not self.public_state_delta:
            raise ValueError("continue_reasoning requires public_state_delta")
        if self.action in {"abstain", "complete"} and not self.stop_reason:
            raise ValueError(f"{self.action} requires stop_reason")

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
class ParsedAgentTurn:
    payload: AgentTurnPayload
    response_sha256: str
    partial: bool = False
    truncation_reason: str = ""
    parse_tier: str = "strict_json"
    recovery_reason: str = ""
    assurance_degradation: str = "none"


AGENT_TURN_FIELDS = frozenset(
    {
        "protocol_version",
        "task_result_type",
        "action",
        "public_state_delta",
        "result_payload",
        "outbound_intents",
        "progress_summary",
        "stop_reason",
    }
)
_MODEL_TURN_FIELDS = AGENT_TURN_FIELDS
_HOST_OWNED_TURN_FIELDS = frozenset(
    {
        "agent_id",
        "task_id",
        "turn_id",
        "artifact_id",
        "message_id",
        "thread_id",
        "session_id",
        "requested_max_output_tokens",
        "stage_timeout_seconds",
    }
)


class AgentTurnPayloadParser:
    """Parse the model-owned public Action envelope without accepting Host IDs."""

    def parse(
        self,
        response: str,
        *,
        allowed_actions: tuple[str, ...] | frozenset[str] | None = None,
        truncated: bool = False,
        truncation_reason: str = "",
    ) -> ParsedAgentTurn:
        recovery = StructuredOutputRecoveryLayer()
        model_text = prepare_model_text(response)
        raw_response = model_text.public_text
        truncated = truncated or model_text.think_truncated
        if any(
            re.search(rf'"{re.escape(field)}"\s*:', raw_response)
            for field in _HOST_OWNED_TURN_FIELDS
        ):
            raise ValueError("AgentTurnPayload contains Host-owned fields")
        try:
            recovered = recovery.parse_object(
                raw_response,
                truncated=truncated,
            )
            decoded = recovered.value
        except (TypeError, ValueError) as error:
            decoded = None
            decoded = self._semantic_salvage(recovery, raw_response)
            if decoded is None:
                raise ValueError("AgentTurnPayload is not valid JSON") from error
            recovered_tier = "semantic_salvage"
            recovered_reason = "complete_public_fields_from_truncated_turn"
            recovered_degradation = "high"
        else:
            recovered_tier = recovered.parse_tier
            recovered_reason = recovered.recovery_reason
            recovered_degradation = recovered.assurance_degradation
        if not isinstance(decoded, dict) or set(decoded) != _MODEL_TURN_FIELDS:
            semantic = self._semantic_salvage(recovery, raw_response)
            if semantic is not None:
                decoded = semantic
                recovered_tier = "semantic_salvage"
                recovered_reason = "complete_public_fields_from_truncated_turn"
                recovered_degradation = "high"
            else:
                raise ValueError("AgentTurnPayload fields do not match the public schema")
        self._reject_host_fields(decoded)
        outbound = decoded["outbound_intents"]
        if not isinstance(outbound, list):
            raise ValueError("AgentTurnPayload outbound_intents must be a list")
        payload = AgentTurnPayload(
            protocol_version=str(decoded["protocol_version"]),
            task_result_type=str(decoded["task_result_type"]).strip(),
            action=str(decoded["action"]).strip(),
            public_state_delta=deepcopy(decoded["public_state_delta"]),
            result_payload=deepcopy(decoded["result_payload"]),
            outbound_intents=tuple(deepcopy(item) for item in outbound),
            progress_summary=str(decoded["progress_summary"]).strip(),
            stop_reason=str(decoded["stop_reason"]).strip(),
        )
        if allowed_actions is not None and payload.action not in set(allowed_actions):
            raise ValueError("AgentTurnPayload action is not allowed for this Turn")
        reason = str(truncation_reason).strip()
        return ParsedAgentTurn(
            payload=payload,
            response_sha256=sha256(raw_response.encode("utf-8")).hexdigest(),
            partial=bool(truncated),
            truncation_reason=reason if truncated else "",
            parse_tier=recovered_tier,
            recovery_reason=recovered_reason,
            assurance_degradation=recovered_degradation,
        )

    @staticmethod
    def _semantic_salvage(
        recovery: StructuredOutputRecoveryLayer,
        response: str,
    ) -> dict[str, Any] | None:
        fields = recovery.salvage_top_level_fields(response, _MODEL_TURN_FIELDS)
        action = fields.get("action")
        result_payload = fields.get("result_payload")
        public_delta = fields.get("public_state_delta")
        if not isinstance(action, str):
            return None
        if not isinstance(result_payload, dict) and not isinstance(
            public_delta, dict
        ):
            return None
        task_result_type = fields.get("task_result_type")
        if not isinstance(task_result_type, str) or not task_result_type.strip():
            return None
        return {
            "protocol_version": str(
                fields.get("protocol_version", PROTOCOL_SCHEMA_VERSION)
            ),
            "task_result_type": task_result_type,
            "action": action,
            "public_state_delta": (
                public_delta if isinstance(public_delta, dict) else {}
            ),
            "result_payload": (
                result_payload if isinstance(result_payload, dict) else {}
            ),
            "outbound_intents": (
                fields["outbound_intents"]
                if isinstance(fields.get("outbound_intents"), list)
                else []
            ),
            "progress_summary": str(
                fields.get("progress_summary", "Recovered public Agent result")
            ),
            "stop_reason": str(
                fields.get("stop_reason", "response_truncated_after_public_result")
            ),
        }

    def _reject_host_fields(self, value: Any) -> None:
        if isinstance(value, dict):
            forbidden = _HOST_OWNED_TURN_FIELDS.intersection(value)
            if forbidden:
                raise ValueError(
                    "AgentTurnPayload contains Host-owned fields: "
                    + ", ".join(sorted(forbidden))
                )
            for nested in value.values():
                self._reject_host_fields(nested)
        elif isinstance(value, list):
            for nested in value:
                self._reject_host_fields(nested)


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
    input_artifact_ids: tuple[str, ...] = ()
    recipient_agent_id: str = ""
    thread_id: str = ""
    reply_to_message_id: str = ""
    close_thread_after_publish: bool = False
    plan_version: int = 0
    shared_context_hash: str = ""
    branch_context_hash: str = ""

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
            "input_artifact_ids": list(self.input_artifact_ids),
            "recipient_agent_id": self.recipient_agent_id,
            "thread_id": self.thread_id,
            "reply_to_message_id": self.reply_to_message_id,
            "close_thread_after_publish": self.close_thread_after_publish,
            "plan_version": self.plan_version,
            "shared_context_hash": self.shared_context_hash,
            "branch_context_hash": self.branch_context_hash,
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
