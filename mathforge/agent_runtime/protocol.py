from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
import re
from typing import Any

from mathforge.parsing.answer_extraction import prepare_model_text
from mathforge.parsing.structured_output import StructuredOutputRecoveryLayer


PROTOCOL_SCHEMA_VERSION = "1.0"
LITE_PROTOCOL_SCHEMA_VERSION = "1.1-lite"
AGENT_TURN_PROTOCOL_VARIANTS = frozenset(
    {PROTOCOL_SCHEMA_VERSION, LITE_PROTOCOL_SCHEMA_VERSION}
)

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


LITE_AGENT_TURN_FIELDS = frozenset(
    {"action", "payload", "outbound", "stop_reason"}
)
# Friendly aliases make the experiment discoverable without changing the
# production 1.0 type imported by existing callers.
AGENT_TURN_LITE_FIELDS = LITE_AGENT_TURN_FIELDS


def _lite_default_result_type(action: str) -> str:
    return {
        "publish_candidate": "CandidateArtifact",
        "request_tool_check": "ToolRequestArtifact",
        "challenge_candidate": "CritiqueArtifact",
        "publish_rebuttal": "RebuttalArtifact",
        "complete": "CandidateArtifact",
        "abstain": "CheckpointArtifact",
    }.get(action, "ProgressArtifact")


@dataclass(frozen=True)
class AgentTurnPayloadLite:
    """Model-owned 1.1-lite turn payload.

    The model emits only an Action, mathematical/public payload, optional
    outbound intent data, and a stop reason.  The Host wraps it into the
    existing 1.0 envelope after assigning task/result/identity metadata.
    """

    action: str
    payload: dict[str, Any]
    outbound: tuple[dict[str, Any], ...] = ()
    stop_reason: str = ""

    def __post_init__(self) -> None:
        if self.action not in ACTION_TYPES:
            raise ValueError("invalid AgentTurnPayload 1.1-lite action")
        if not isinstance(self.payload, dict):
            raise ValueError("AgentTurnPayload 1.1-lite payload must be an object")
        if not isinstance(self.outbound, tuple) or any(
            not isinstance(item, dict) for item in self.outbound
        ):
            raise ValueError("AgentTurnPayload 1.1-lite outbound must contain objects")
        forbidden = _nested_host_fields(
            self.payload,
            fields=_LITE_HOST_OWNED_FIELDS,
        )
        if forbidden:
            raise ValueError(
                "AgentTurnPayload 1.1-lite payload contains Host-owned fields: "
                + ", ".join(sorted(forbidden))
            )
        if self.action in {"publish_candidate", "continue_reasoning"} and not self.payload:
            raise ValueError(
                f"{self.action} requires a non-empty 1.1-lite payload"
            )
        if self.action in {"abstain", "complete"} and not str(self.stop_reason).strip():
            raise ValueError(f"{self.action} requires stop_reason")

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "payload": deepcopy(self.payload),
            "outbound": [deepcopy(item) for item in self.outbound],
            "stop_reason": self.stop_reason,
        }

    def to_agent_turn(
        self,
        *,
        task_result_type: str = "",
        progress_summary: str = "",
        protocol_version: str = PROTOCOL_SCHEMA_VERSION,
    ) -> "AgentTurnPayload":
        """Wrap the lite result with deterministic Host-owned defaults."""

        if protocol_version not in AGENT_TURN_PROTOCOL_VARIANTS:
            raise ValueError("unsupported AgentTurnPayload protocol version")
        result_type = str(task_result_type or "").strip() or _lite_default_result_type(
            self.action
        )
        is_progress = self.action == "continue_reasoning" or result_type in {
            "ProgressArtifact",
            "ToolRequestArtifact",
            "CheckpointArtifact",
        }
        return AgentTurnPayload(
            protocol_version=PROTOCOL_SCHEMA_VERSION,
            task_result_type=result_type,
            action=self.action,
            public_state_delta=deepcopy(self.payload) if is_progress else {},
            result_payload=deepcopy(self.payload) if not is_progress else {},
            outbound_intents=tuple(deepcopy(item) for item in self.outbound),
            progress_summary=(
                str(progress_summary).strip()
                or str(self.stop_reason).strip()
                or "Host-wrapped 1.1-lite result"
            ),
            stop_reason=str(self.stop_reason).strip(),
        )


AgentTurnPayload11Lite = AgentTurnPayloadLite


@dataclass(frozen=True)
class ParsedAgentTurn:
    payload: AgentTurnPayload
    response_sha256: str
    partial: bool = False
    truncation_reason: str = ""
    parse_tier: str = "strict_json"
    recovery_reason: str = ""
    assurance_degradation: str = "none"


@dataclass(frozen=True)
class ParsedAgentTurnLite:
    payload: AgentTurnPayloadLite
    response_sha256: str
    partial: bool = False
    truncation_reason: str = ""
    parse_tier: str = "strict_json"
    recovery_reason: str = ""
    assurance_degradation: str = "none"

    def to_agent_turn(
        self,
        *,
        task_result_type: str = "",
        progress_summary: str = "",
    ) -> ParsedAgentTurn:
        wrapped = self.payload.to_agent_turn(
            task_result_type=task_result_type,
            progress_summary=progress_summary,
        )
        return ParsedAgentTurn(
            payload=wrapped,
            response_sha256=self.response_sha256,
            partial=self.partial,
            truncation_reason=self.truncation_reason,
            parse_tier=f"lite:{self.parse_tier}",
            recovery_reason=self.recovery_reason,
            assurance_degradation=self.assurance_degradation,
        )


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


def _nested_host_fields(
    value: Any,
    *,
    fields: frozenset[str] | None = None,
) -> set[str]:
    found: set[str] = set()
    owned_fields = _HOST_OWNED_TURN_FIELDS if fields is None else fields
    if isinstance(value, dict):
        found.update(owned_fields.intersection(value))
        for nested in value.values():
            found.update(_nested_host_fields(nested, fields=fields))
    elif isinstance(value, list):
        for nested in value:
            found.update(_nested_host_fields(nested, fields=fields))
    return found


_LITE_HOST_OWNED_FIELDS = frozenset(
    {
        *_HOST_OWNED_TURN_FIELDS,
        "priority",
        "status",
        "token_limit",
        "token_limits",
        "max_tokens",
        "max_output_tokens",
        "token_budget",
        "timeout",
        "timeout_seconds",
        "protocol_version",
        "task_result_type",
        "public_state_delta",
        "result_payload",
        "outbound_intents",
        "progress_summary",
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

    def parse_lite(
        self,
        response: str,
        *,
        allowed_actions: tuple[str, ...] | frozenset[str] | None = None,
        truncated: bool = False,
        truncation_reason: str = "",
    ) -> "ParsedAgentTurnLite":
        """Parse the experimental 1.1-lite model envelope."""

        recovery = StructuredOutputRecoveryLayer()
        model_text = prepare_model_text(response)
        raw_response = model_text.public_text
        truncated = truncated or model_text.think_truncated
        if any(
            re.search(rf'"{re.escape(field)}"\s*:', raw_response)
            for field in _LITE_HOST_OWNED_FIELDS
        ):
            raise ValueError("AgentTurnPayload 1.1-lite contains Host-owned fields")
        try:
            recovered = recovery.parse_object(raw_response, truncated=truncated)
            decoded = recovered.value
            parse_tier = recovered.parse_tier
            recovery_reason = recovered.recovery_reason
            degradation = recovered.assurance_degradation
        except (TypeError, ValueError) as error:
            decoded = self._semantic_salvage_lite(recovery, raw_response)
            if decoded is None:
                raise ValueError("AgentTurnPayload 1.1-lite is not valid JSON") from error
            parse_tier = "semantic_salvage"
            recovery_reason = "complete_lite_public_fields_from_truncated_turn"
            degradation = "high"
        if not isinstance(decoded, dict) or set(decoded) != LITE_AGENT_TURN_FIELDS:
            semantic = self._semantic_salvage_lite(recovery, raw_response)
            if semantic is None:
                raise ValueError(
                    "AgentTurnPayload 1.1-lite fields do not match the public schema"
                )
            decoded = semantic
            parse_tier = "semantic_salvage"
            recovery_reason = "complete_lite_public_fields_from_truncated_turn"
            degradation = "high"
        forbidden = _nested_host_fields(decoded, fields=_LITE_HOST_OWNED_FIELDS)
        if forbidden:
            raise ValueError(
                "AgentTurnPayload 1.1-lite contains Host-owned fields: "
                + ", ".join(sorted(forbidden))
            )
        outbound = decoded["outbound"]
        if not isinstance(outbound, list):
            raise ValueError("AgentTurnPayload 1.1-lite outbound must be a list")
        payload = AgentTurnPayloadLite(
            action=str(decoded["action"]).strip(),
            payload=deepcopy(decoded["payload"]),
            outbound=tuple(deepcopy(item) for item in outbound),
            stop_reason=str(decoded["stop_reason"]).strip(),
        )
        if allowed_actions is not None and payload.action not in set(allowed_actions):
            raise ValueError("AgentTurnPayload 1.1-lite action is not allowed")
        reason = str(truncation_reason).strip()
        return ParsedAgentTurnLite(
            payload=payload,
            response_sha256=sha256(raw_response.encode("utf-8")).hexdigest(),
            partial=bool(truncated),
            truncation_reason=reason if truncated else "",
            parse_tier=parse_tier,
            recovery_reason=recovery_reason,
            assurance_degradation=degradation,
        )

    @staticmethod
    def _semantic_salvage_lite(
        recovery: StructuredOutputRecoveryLayer,
        response: str,
    ) -> dict[str, Any] | None:
        fields = recovery.salvage_top_level_fields(response, LITE_AGENT_TURN_FIELDS)
        action = fields.get("action")
        payload = fields.get("payload")
        if not isinstance(action, str) or not isinstance(payload, dict):
            return None
        return {
            "action": action,
            "payload": payload,
            "outbound": (
                fields["outbound"]
                if isinstance(fields.get("outbound"), list)
                else []
            ),
            "stop_reason": str(fields.get("stop_reason", "")),
        }

    def parse_any(
        self,
        response: str,
        *,
        protocol_version: str = PROTOCOL_SCHEMA_VERSION,
        allowed_actions: tuple[str, ...] | frozenset[str] | None = None,
        truncated: bool = False,
        truncation_reason: str = "",
        task_result_type: str = "",
        progress_summary: str = "",
    ) -> ParsedAgentTurn:
        if protocol_version == LITE_PROTOCOL_SCHEMA_VERSION:
            lite = self.parse_lite(
                response,
                allowed_actions=allowed_actions,
                truncated=truncated,
                truncation_reason=truncation_reason,
            )
            return lite.to_agent_turn(
                task_result_type=task_result_type,
                progress_summary=progress_summary,
            )
        if protocol_version != PROTOCOL_SCHEMA_VERSION:
            raise ValueError("unsupported AgentTurnPayload protocol version")
        return self.parse(
            response,
            allowed_actions=allowed_actions,
            truncated=truncated,
            truncation_reason=truncation_reason,
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


@dataclass
class AgentTurnABMetrics:
    """Comparable P0/P1 measurements for the lite-envelope experiment."""

    variant: str
    calls: int = 0
    json_valid: int = 0
    truncations: int = 0
    accuracy_successes: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0

    def __post_init__(self) -> None:
        if self.variant not in {"P0", "P1"}:
            raise ValueError("AgentTurnABMetrics variant must be P0 or P1")

    def record(
        self,
        *,
        json_valid: bool,
        truncated: bool,
        accurate: bool | None = None,
        output_tokens: int = 0,
        latency_ms: float = 0.0,
    ) -> None:
        self.calls += 1
        self.json_valid += int(bool(json_valid))
        self.truncations += int(bool(truncated))
        if accurate is not None:
            self.accuracy_successes += int(bool(accurate))
        self.output_tokens += max(0, int(output_tokens))
        self.latency_ms += max(0.0, float(latency_ms))

    @property
    def json_valid_rate(self) -> float:
        return self.json_valid / self.calls if self.calls else 0.0

    @property
    def truncation_rate(self) -> float:
        return self.truncations / self.calls if self.calls else 0.0

    @property
    def accuracy_rate(self) -> float:
        return self.accuracy_successes / self.calls if self.calls else 0.0

    @property
    def mean_output_tokens(self) -> float:
        return self.output_tokens / self.calls if self.calls else 0.0

    @property
    def mean_latency_ms(self) -> float:
        return self.latency_ms / self.calls if self.calls else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant": self.variant,
            "calls": self.calls,
            "json_valid": self.json_valid,
            "json_valid_rate": round(self.json_valid_rate, 6),
            "truncations": self.truncations,
            "truncation_rate": round(self.truncation_rate, 6),
            "accuracy_successes": self.accuracy_successes,
            "accuracy_rate": round(self.accuracy_rate, 6),
            "output_tokens": self.output_tokens,
            "mean_output_tokens": round(self.mean_output_tokens, 6),
            "latency_ms": round(self.latency_ms, 6),
            "mean_latency_ms": round(self.mean_latency_ms, 6),
        }


@dataclass(frozen=True)
class AgentTurnABDecision:
    winner: str
    migration_eligible: bool
    reason_codes: tuple[str, ...]
    p0: dict[str, Any]
    p1: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "winner": self.winner,
            "migration_eligible": self.migration_eligible,
            "reason_codes": list(self.reason_codes),
            "p0": deepcopy(self.p0),
            "p1": deepcopy(self.p1),
        }


@dataclass
class AgentTurnABExperiment:
    """Record P0 (1.0) and P1 (1.1-lite) without changing production policy."""

    p0: AgentTurnABMetrics = field(
        default_factory=lambda: AgentTurnABMetrics("P0")
    )
    p1: AgentTurnABMetrics = field(
        default_factory=lambda: AgentTurnABMetrics("P1")
    )

    def metrics(self, variant: str) -> AgentTurnABMetrics:
        if variant == "P0":
            return self.p0
        if variant == "P1":
            return self.p1
        raise ValueError("AgentTurnABExperiment variant must be P0 or P1")

    def record(self, variant: str, **kwargs: Any) -> None:
        self.metrics(variant).record(**kwargs)

    def evaluate(self) -> AgentTurnABDecision:
        p0 = self.p0
        p1 = self.p1
        reasons: list[str] = []
        if not p0.calls or not p1.calls:
            reasons.append("both_variants_require_observations")
            return AgentTurnABDecision(
                "undetermined",
                False,
                tuple(reasons),
                p0.to_dict(),
                p1.to_dict(),
            )
        no_regression = (
            p1.json_valid_rate >= p0.json_valid_rate
            and p1.accuracy_rate >= p0.accuracy_rate
            and p1.truncation_rate <= p0.truncation_rate
            and p1.mean_output_tokens <= p0.mean_output_tokens
            and p1.mean_latency_ms <= p0.mean_latency_ms
        )
        strict_improvement = (
            p1.json_valid_rate > p0.json_valid_rate
            or p1.accuracy_rate > p0.accuracy_rate
            or p1.truncation_rate < p0.truncation_rate
            or p1.mean_output_tokens < p0.mean_output_tokens
            or p1.mean_latency_ms < p0.mean_latency_ms
        )
        if no_regression and strict_improvement:
            reasons.append("p1_non_regression_with_strict_improvement")
            return AgentTurnABDecision(
                "P1", True, tuple(reasons), p0.to_dict(), p1.to_dict()
            )
        reasons.append("p1_did_not_win_all_required_metrics")
        return AgentTurnABDecision(
            "P0", False, tuple(reasons), p0.to_dict(), p1.to_dict()
        )


LiteAgentTurnABExperiment = AgentTurnABExperiment
AgentTurnAB = AgentTurnABExperiment
AgentTurnLitePayload = AgentTurnPayloadLite
ParsedAgentTurn11Lite = ParsedAgentTurnLite


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
