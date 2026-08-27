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
_PHASE_ACTIONS = {
    # Router turns publish a route/plan through the non-agent-action path;
    # keep the same phase authority for both initial routing and replans.
    "router": frozenset(
        {"continue_reasoning", "send_message", "complete", "abstain"}
    ),
    "replan": frozenset(
        {"continue_reasoning", "send_message", "complete", "abstain"}
    ),
    "solve": frozenset(
        {
            "continue_reasoning",
            "publish_candidate",
            "request_tool_check",
            "request_lemma",
            "send_message",
            "request_peer_review",
            "request_replan",
            "abstain",
            "complete",
        }
    ),
    "progress": frozenset(
        {
            "continue_reasoning",
            "request_lemma",
            "request_tool_check",
            "request_replan",
            "complete",
            "abstain",
        }
    ),
    "candidate": frozenset({"publish_candidate", "abstain"}),
    "peer_review": frozenset(
        {"challenge_candidate", "send_message", "complete", "abstain"}
    ),
    "rebuttal": frozenset(
        {"publish_rebuttal", "send_message", "complete", "abstain"}
    ),
    "lemma": frozenset(
        {"continue_reasoning", "send_message", "complete", "abstain"}
    ),
    "verifier": frozenset(
        {
            "continue_reasoning",
            "challenge_candidate",
            "request_tool_check",
            "request_replan",
            "request_repair",
            "send_message",
            "complete",
            "abstain",
        }
    ),
    "final_audit": frozenset(
        {"request_replan", "request_repair", "send_message", "complete", "abstain"}
    ),
    "repair": frozenset(
        {"continue_reasoning", "request_tool_check", "send_message", "complete", "abstain"}
    ),
    "finalize": frozenset({"send_message", "complete", "abstain"}),
}
_PROMPT_PHASE_ACTIONS = {
    "peer_review_turn": frozenset({"challenge_candidate"}),
    "rebuttal_turn": frozenset({"publish_rebuttal"}),
    "lemma_turn": frozenset({"complete", "abstain"}),
    "verifier_turn": frozenset({"challenge_candidate"}),
    "final_audit_turn": frozenset({"complete"}),
}
_STATIC_ROUTES = {
    "continue_reasoning": ("ProgressArtifact", "progress_shared", "RouterPlanner"),
    "request_lemma": ("ProgressArtifact", "lemma_requested", "LemmaCurator"),
    "request_tool_check": ("ToolRequestArtifact", "tool_check_requested", "RouterPlanner"),
    "request_replan": ("ProgressArtifact", "replan_requested", "RouterPlanner"),
    "request_repair": ("CritiqueArtifact", "repair_requested", "RepairAgent"),
    "publish_candidate": ("CandidateArtifact", "candidate_published", "VerifierSkeptic"),
    "request_peer_review": ("ProgressArtifact", "peer_review_requested", "VerifierSkeptic"),
    "abstain": ("CheckpointArtifact", "task_abstained", "RouterPlanner"),
}


class ActionRegistry:
    """Single source for declared actions, authorization, and Host routing."""

    def __init__(self) -> None:
        declared = set().union(*_ROLE_ACTIONS.values())
        if not declared <= ACTION_TYPES:
            raise ValueError("ActionRegistry contains unknown actions")
        missing_handlers = sorted(
            action
            for action in declared
            if action != "send_message" and action not in _STATIC_ROUTES
            and action not in {"challenge_candidate", "publish_rebuttal", "complete"}
        )
        if missing_handlers:
            raise ValueError(
                "ActionRegistry actions have no Host handler: "
                + ", ".join(missing_handlers)
            )
        for phase, actions in {**_PHASE_ACTIONS, **_PROMPT_PHASE_ACTIONS}.items():
            if not actions <= declared:
                raise ValueError(
                    f"ActionRegistry phase {phase} contains undeclared actions"
                )

    @property
    def declared_actions(self) -> frozenset[str]:
        return frozenset().union(*_ROLE_ACTIONS.values())

    def actions_for(
        self,
        role: str,
        *,
        phase: str | None = None,
    ) -> frozenset[str]:
        actions = _ROLE_ACTIONS.get(role, frozenset())
        if phase is None:
            return actions
        phase_actions = _PHASE_ACTIONS.get(
            phase,
            _PROMPT_PHASE_ACTIONS.get(phase, frozenset()),
        )
        return frozenset(actions.intersection(phase_actions))

    def prompt_actions(self, role: str, *, phase: str | None = None) -> tuple[str, ...]:
        """Return the canonical action enum for a role-facing prompt."""

        return tuple(sorted(self.actions_for(role, phase=phase)))

    def has_handler(self, action: str) -> bool:
        return str(action) in {
            *self.declared_actions,
        } and (
            str(action) == "send_message"
            or str(action) in _STATIC_ROUTES
            or str(action) in {"challenge_candidate", "publish_rebuttal", "complete"}
        )

    def validate(self) -> None:
        missing = sorted(action for action in self.declared_actions if not self.has_handler(action))
        if missing:
            raise ValueError(
                "ActionRegistry actions have no Host handler: "
                + ", ".join(missing)
            )

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
            **_STATIC_ROUTES,
            "challenge_candidate": (
                "CritiqueArtifact" if context.role == "VerifierSkeptic" else "PeerReviewArtifact",
                "conflict_escalated" if context.role == "VerifierSkeptic" else "peer_review_published",
                context.recipient_role,
            ),
            "publish_rebuttal": ("RebuttalArtifact", "rebuttal_published", context.recipient_role),
            "complete": (context.artifact_type, context.message_type, context.recipient_role),
        }
        route = routes.get(payload.action)
        if route is None:
            raise ValueError("Agent Action has no Host handler")
        if payload.task_result_type != route[0]:
            raise ValueError("Agent Action task_result_type is inconsistent")
        return ActionHandler(payload.action, *route)
