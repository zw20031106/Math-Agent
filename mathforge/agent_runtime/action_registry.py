from __future__ import annotations

from dataclasses import dataclass

from mathforge.agent_runtime.protocol import ACTION_TYPES, AgentTurnPayload, TurnContext


@dataclass(frozen=True)
class ActionHandler:
    action: str
    artifact_type: str
    message_type: str
    recipient_role: str


_ROLE_ACTIONS = {
    "RouterPlanner": frozenset({"continue_reasoning", "send_message", "complete", "abstain"}),
    "PrimarySolver": frozenset({"continue_reasoning", "publish_candidate", "request_tool_check", "request_lemma", "send_message", "request_peer_review", "challenge_candidate", "publish_rebuttal", "request_replan", "abstain", "complete"}),
    "AlternativeSolver": frozenset({"continue_reasoning", "publish_candidate", "request_tool_check", "request_lemma", "send_message", "request_peer_review", "challenge_candidate", "publish_rebuttal", "request_replan", "abstain", "complete"}),
    "LemmaCurator": frozenset({"continue_reasoning", "send_message", "complete", "abstain"}),
    "VerifierSkeptic": frozenset({"continue_reasoning", "challenge_candidate", "request_tool_check", "request_replan", "request_repair", "send_message", "complete", "abstain"}),
    "RepairAgent": frozenset({"continue_reasoning", "request_tool_check", "send_message", "complete", "abstain"}),
    "LLMFinalizer": frozenset({"send_message", "complete", "abstain"}),
}
_BUSINESS_MESSAGE_TYPES = frozenset({"progress_shared"})
_BUSINESS_RECIPIENT_ROLES = frozenset(_ROLE_ACTIONS)


class ActionRegistry:
    """Single source for declared actions, authorization, and Host routing."""

    def __init__(self) -> None:
        declared = set().union(*_ROLE_ACTIONS.values())
        if not declared <= ACTION_TYPES:
            raise ValueError("ActionRegistry contains unknown actions")

    def actions_for(self, role: str) -> frozenset[str]:
        return _ROLE_ACTIONS.get(role, frozenset())

    def resolve(self, context: TurnContext, payload: AgentTurnPayload) -> ActionHandler:
        if payload.action not in self.actions_for(context.role):
            raise ValueError("Agent Action is not authorized for this role")
        if payload.action == "send_message":
            if len(payload.outbound_intents) != 1:
                raise ValueError("send_message requires one business intent")
            intent = payload.outbound_intents[0]
            if set(intent) != {"recipient_role", "message_type"}:
                raise ValueError("send_message business intent fields are invalid")
            recipient_role = str(intent["recipient_role"])
            message_type = str(intent["message_type"])
            if (
                recipient_role not in _BUSINESS_RECIPIENT_ROLES
                or message_type not in _BUSINESS_MESSAGE_TYPES
            ):
                raise ValueError("send_message business intent is not supported")
            if payload.task_result_type != "ProgressArtifact":
                raise ValueError("Agent Action task_result_type is inconsistent")
            return ActionHandler(
                payload.action,
                "ProgressArtifact",
                message_type,
                recipient_role,
            )
        routes = {
            "continue_reasoning": ("ProgressArtifact", "progress_shared", "RouterPlanner"),
            "request_lemma": ("ProgressArtifact", "lemma_requested", "LemmaCurator"),
            "request_tool_check": ("ToolRequestArtifact", "tool_check_requested", "RouterPlanner"),
            "request_replan": ("ProgressArtifact", "replan_requested", "RouterPlanner"),
            "request_repair": ("CritiqueArtifact", "repair_requested", "RepairAgent"),
            "publish_candidate": ("CandidateArtifact", "candidate_published", "VerifierSkeptic"),
            "challenge_candidate": (
                "CritiqueArtifact" if context.role == "VerifierSkeptic" else "PeerReviewArtifact",
                "conflict_escalated" if context.role == "VerifierSkeptic" else "peer_review_published",
                context.recipient_role,
            ),
            "publish_rebuttal": ("RebuttalArtifact", "rebuttal_published", context.recipient_role),
            "request_peer_review": ("ProgressArtifact", "peer_review_requested", "VerifierSkeptic"),
            "abstain": ("CheckpointArtifact", "task_abstained", "RouterPlanner"),
            "complete": (context.artifact_type, context.message_type, context.recipient_role),
        }
        route = routes.get(payload.action)
        if route is None:
            raise ValueError("Agent Action has no Host handler")
        if payload.task_result_type != route[0]:
            raise ValueError("Agent Action task_result_type is inconsistent")
        return ActionHandler(payload.action, *route)
