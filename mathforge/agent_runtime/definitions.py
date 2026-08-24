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
        from mathforge.agent_runtime.action_registry import ActionRegistry
        from mathforge.agent_runtime.permissions import permissions_for_role
        from mathforge.agents.registry import PromptContractLoader

        actions = ActionRegistry()
        contracts = PromptContractLoader()
        delivery_only_messages = {
            "PrimarySolver": {"audit_published", "rebuttal_published"},
            "AlternativeSolver": {"audit_published", "rebuttal_published"},
        }

        def role_permissions(role: str) -> tuple[tuple[str, ...], ...]:
            permissions = permissions_for_role(role)
            return (
                tuple(
                    sorted(
                        set().union(
                            *(item.accepted_message_types for item in permissions)
                        )
                        | delivery_only_messages.get(role, set())
                    )
                ),
                tuple(
                    sorted(
                        set().union(
                            *(item.readable_artifact_types for item in permissions)
                        )
                    )
                ),
                tuple(
                    sorted(
                        set().union(
                            *(item.writable_artifact_types for item in permissions)
                        )
                    )
                ),
            )

        def build(
            role: str,
            modes: tuple[str, ...],
            tasks: tuple[str, ...],
            prompt_contract: str,
        ) -> AgentDefinition:
            messages, readable, writable = role_permissions(role)
            return _definition(
                role,
                modes,
                tasks,
                messages,
                readable,
                writable,
                tuple(sorted(actions.actions_for(role))),
                prompt_contract,
                contracts.load(prompt_contract).fields["version"],
            )

        return cls(
            (
                build(
                    "RouterPlanner",
                    ("plan", "replan"),
                    ("route_and_plan", "replan"),
                    "router_planner",
                ),
                build(
                    "PrimarySolver",
                    ("solve", "peer_review", "rebuttal"),
                    ("solve_primary", "continue_reasoning", "peer_review_candidate", "respond_to_peer_review", "solve_new_branch"),
                    "primary_solver",
                ),
                build(
                    "AlternativeSolver",
                    ("solve", "peer_review", "rebuttal"),
                    ("solve_alternative", "continue_reasoning", "peer_review_candidate", "respond_to_peer_review", "solve_new_branch"),
                    "alternative_solver",
                ),
                build(
                    "LemmaCurator",
                    ("curate", "answer_request"),
                    ("curate_lemmas", "answer_lemma_request"),
                    "lemma_curator",
                ),
                build(
                    "VerifierSkeptic",
                    ("cross_exam", "final_audit"),
                    ("cross_exam_candidates", "final_audit"),
                    "verifier_skeptic",
                ),
                build(
                    "RepairAgent",
                    ("repair",),
                    ("repair_claims",),
                    "repair",
                ),
                build(
                    "LLMFinalizer",
                    ("finalize",),
                    ("copy_finalize",),
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
    prompt_version: str,
) -> AgentDefinition:
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
        prompt_version=str(prompt_version),
        skill_roles=(role,),
        failure_policy="record_public_failure_and_return_control_to_host",
    )
