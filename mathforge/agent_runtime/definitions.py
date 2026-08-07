from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from mathforge.agent_runtime.protocol import (
    ACTION_TYPES,
    ARTIFACT_TYPES,
    MESSAGE_TYPES,
    TASK_TYPES,
)


@dataclass(frozen=True)
class AgentDefinition:
    role: str
    capabilities: tuple[str, ...]
    allowed_modes: tuple[str, ...]
    accepted_task_types: tuple[str, ...]
    accepted_message_types: tuple[str, ...]
    readable_artifact_types: tuple[str, ...]
    writable_artifact_types: tuple[str, ...]
    allowed_action_types: tuple[str, ...]
    prompt_contract: str
    prompt_version: str
    skill_roles: tuple[str, ...]
    failure_policy: str

    def __post_init__(self) -> None:
        if not self.role or not self.allowed_modes:
            raise ValueError("AgentDefinition role and modes are required")
        if not set(self.accepted_task_types) <= TASK_TYPES:
            raise ValueError("AgentDefinition has invalid task types")
        if not set(self.accepted_message_types) <= MESSAGE_TYPES:
            raise ValueError("AgentDefinition has invalid message types")
        if not set(self.readable_artifact_types) <= ARTIFACT_TYPES:
            raise ValueError("AgentDefinition has invalid readable artifacts")
        if not set(self.writable_artifact_types) <= ARTIFACT_TYPES:
            raise ValueError("AgentDefinition has invalid writable artifacts")
        if not set(self.allowed_action_types) <= ACTION_TYPES:
            raise ValueError("AgentDefinition has invalid actions")


class AgentRegistry:
    """Read-only Agent definitions shared safely by every solve."""

    def __init__(self, definitions: tuple[AgentDefinition, ...]) -> None:
        records = {definition.role: definition for definition in definitions}
        if len(records) != len(definitions):
            raise ValueError("AgentDefinition roles must be unique")
        self._definitions: Mapping[str, AgentDefinition] = MappingProxyType(records)

    @classmethod
    def default(cls) -> "AgentRegistry":
        common_messages = tuple(sorted(MESSAGE_TYPES))
        common_actions = tuple(sorted(ACTION_TYPES))
        common_read = tuple(sorted(ARTIFACT_TYPES))
        return cls(
            (
                _definition(
                    "RouterPlanner",
                    ("plan", "replan"),
                    ("route_and_plan", "replan"),
                    common_messages,
                    common_read,
                    ("RouteArtifact", "PlanArtifact", "ProgressArtifact", "CheckpointArtifact"),
                    common_actions,
                    "router_planner",
                ),
                _definition(
                    "PrimarySolver",
                    ("solve", "peer_review", "rebuttal"),
                    ("solve_primary", "continue_reasoning", "peer_review_candidate", "respond_to_peer_review", "solve_new_branch"),
                    common_messages,
                    common_read,
                    ("ProgressArtifact", "CandidateArtifact", "ToolRequestArtifact", "PeerReviewArtifact", "RebuttalArtifact", "CheckpointArtifact"),
                    common_actions,
                    "primary_solver",
                ),
                _definition(
                    "AlternativeSolver",
                    ("solve", "peer_review", "rebuttal"),
                    ("solve_alternative", "continue_reasoning", "peer_review_candidate", "respond_to_peer_review", "solve_new_branch"),
                    common_messages,
                    common_read,
                    ("ProgressArtifact", "CandidateArtifact", "ToolRequestArtifact", "PeerReviewArtifact", "RebuttalArtifact", "CheckpointArtifact"),
                    common_actions,
                    "alternative_solver",
                ),
                _definition(
                    "LemmaCurator",
                    ("curate", "answer_request"),
                    ("curate_lemmas", "answer_lemma_request"),
                    common_messages,
                    common_read,
                    ("LemmaArtifact", "ProgressArtifact", "CheckpointArtifact"),
                    common_actions,
                    "lemma_curator",
                ),
                _definition(
                    "VerifierSkeptic",
                    ("cross_exam", "final_audit"),
                    ("cross_exam_candidates", "final_audit"),
                    common_messages,
                    common_read,
                    ("PeerReviewArtifact", "CritiqueArtifact", "AuditArtifact", "ProgressArtifact", "CheckpointArtifact"),
                    common_actions,
                    "verifier_skeptic",
                ),
                _definition(
                    "RepairAgent",
                    ("repair",),
                    ("repair_claims",),
                    common_messages,
                    common_read,
                    ("RepairPatchArtifact", "RepairResultArtifact", "CandidateArtifact", "ProgressArtifact", "CheckpointArtifact"),
                    common_actions,
                    "repair",
                ),
                _definition(
                    "LLMFinalizer",
                    ("finalize",),
                    ("copy_finalize",),
                    common_messages,
                    common_read,
                    ("DecisionArtifact", "CandidateArtifact", "ProgressArtifact", "CheckpointArtifact"),
                    common_actions,
                    "finalizer",
                ),
            )
        )

    def get(self, role: str) -> AgentDefinition:
        try:
            return self._definitions[str(role)]
        except KeyError as error:
            raise KeyError(f"unknown Agent role: {role}") from error

    def roles(self) -> tuple[str, ...]:
        return tuple(self._definitions)


def _definition(
    role: str,
    modes: tuple[str, ...],
    tasks: tuple[str, ...],
    messages: tuple[str, ...],
    readable: tuple[str, ...],
    writable: tuple[str, ...],
    actions: tuple[str, ...],
    prompt_contract: str,
) -> AgentDefinition:
    prompt_versions = {
        "RouterPlanner": "3",
        "PrimarySolver": "8",
        "AlternativeSolver": "6",
        "LemmaCurator": "3",
        "VerifierSkeptic": "4",
        "RepairAgent": "4",
        "LLMFinalizer": "3",
    }
    return AgentDefinition(
        role=role,
        capabilities=("independent_model_turn", "artifact_publish", "message_send"),
        allowed_modes=modes,
        accepted_task_types=tasks,
        accepted_message_types=messages,
        readable_artifact_types=readable,
        writable_artifact_types=writable,
        allowed_action_types=actions,
        prompt_contract=prompt_contract,
        prompt_version=prompt_versions[role],
        skill_roles=(role,),
        failure_policy="record_public_failure_and_return_control_to_host",
    )
