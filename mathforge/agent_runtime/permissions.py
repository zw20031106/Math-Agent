from __future__ import annotations

from dataclasses import dataclass

from mathforge.agent_runtime.action_registry import ActionRegistry
from mathforge.agent_runtime.protocol import ACTION_TYPES, ARTIFACT_TYPES, TASK_TYPES


@dataclass(frozen=True)
class PhasePermission:
    readable_artifact_types: frozenset[str]
    writable_artifact_types: frozenset[str]
    allowed_action_types: frozenset[str]
    outbound_message_types: frozenset[str]
    accepted_message_types: frozenset[str]

    def __post_init__(self) -> None:
        if not self.readable_artifact_types <= ARTIFACT_TYPES:
            raise ValueError("phase permission contains an unknown readable Artifact")
        if not self.writable_artifact_types <= ARTIFACT_TYPES:
            raise ValueError("phase permission contains an unknown writable Artifact")
        if not self.allowed_action_types <= ACTION_TYPES:
            raise ValueError("phase permission contains an unknown Action")


_PLAN_READ = {
    "ProblemArtifact",
    "RouteArtifact",
    "PlanArtifact",
    "ProgressArtifact",
    "CheckpointArtifact",
}
_SOLVER_PUBLIC_READ = {
    *_PLAN_READ,
    "LemmaArtifact",
    "EvidenceArtifact",
    "ObligationArtifact",
}
_REVIEW_READ = {
    *_SOLVER_PUBLIC_READ,
    "CandidateArtifact",
    "PeerReviewArtifact",
    "RebuttalArtifact",
    "CritiqueArtifact",
}
_VERIFY_READ = {
    *_REVIEW_READ,
    "RepairPatchArtifact",
    "RepairResultArtifact",
    "ConflictGraphArtifact",
}


def _permission(
    readable: set[str],
    writable: set[str],
    actions: set[str],
    messages: set[str],
    accepted_messages: set[str] | None = None,
) -> PhasePermission:
    return PhasePermission(
        frozenset(readable),
        frozenset(writable),
        frozenset(actions),
        frozenset(messages),
        frozenset(accepted_messages or set()),
    )


_ACTION_REGISTRY = ActionRegistry()


def _actions(role: str, phase: str) -> set[str]:
    return set(_ACTION_REGISTRY.actions_for(role, phase=phase))


_SOLVE_ACTIONS = _actions("PrimarySolver", "solve")
_SOLVE_MESSAGES = {
    "progress_shared",
    "candidate_published",
    "lemma_requested",
    "tool_check_requested",
    "peer_review_requested",
    "replan_requested",
    "task_abstained",
}


_PERMISSIONS: dict[tuple[str, str], PhasePermission] = {
    ("RouterPlanner", "route_and_plan"): _permission(
        _PLAN_READ | {"EvidenceArtifact", "ObligationArtifact"},
        {"RouteArtifact", "PlanArtifact", "ProgressArtifact", "CheckpointArtifact"},
        _actions("RouterPlanner", "router"),
        {"plan_published", "progress_shared", "task_abstained"},
        {"progress_shared", "tool_check_requested", "replan_requested", "task_abstained"},
    ),
    ("RouterPlanner", "replan"): _permission(
        _PLAN_READ | {"EvidenceArtifact", "ObligationArtifact", "CritiqueArtifact"},
        {"RouteArtifact", "PlanArtifact", "ProgressArtifact", "CheckpointArtifact"},
        _actions("RouterPlanner", "router"),
        {"plan_published", "progress_shared", "task_abstained"},
        {"progress_shared", "tool_check_requested", "replan_requested", "task_abstained"},
    ),
    ("PrimarySolver", "solve_primary"): _permission(
        _SOLVER_PUBLIC_READ,
        {"ProgressArtifact", "CandidateArtifact", "ToolRequestArtifact", "CheckpointArtifact"},
        _SOLVE_ACTIONS,
        _SOLVE_MESSAGES,
        {"plan_published", "lemma_published", "evidence_available", "progress_shared"},
    ),
    ("AlternativeSolver", "solve_alternative"): _permission(
        _SOLVER_PUBLIC_READ,
        {"ProgressArtifact", "CandidateArtifact", "ToolRequestArtifact", "CheckpointArtifact"},
        _SOLVE_ACTIONS,
        _SOLVE_MESSAGES,
        {"plan_published", "lemma_published", "evidence_available", "progress_shared"},
    ),
    ("PrimarySolver", "continue_reasoning"): _permission(
        _SOLVER_PUBLIC_READ,
        {"ProgressArtifact", "CandidateArtifact", "ToolRequestArtifact", "CheckpointArtifact"},
        _SOLVE_ACTIONS,
        _SOLVE_MESSAGES,
        {"plan_published", "lemma_published", "evidence_available", "progress_shared"},
    ),
    ("AlternativeSolver", "continue_reasoning"): _permission(
        _SOLVER_PUBLIC_READ,
        {"ProgressArtifact", "CandidateArtifact", "ToolRequestArtifact", "CheckpointArtifact"},
        _SOLVE_ACTIONS,
        _SOLVE_MESSAGES,
        {"plan_published", "lemma_published", "evidence_available", "progress_shared"},
    ),
    ("PrimarySolver", "solve_new_branch"): _permission(
        _VERIFY_READ,
        {"ProgressArtifact", "CandidateArtifact", "ToolRequestArtifact", "CheckpointArtifact"},
        _SOLVE_ACTIONS,
        _SOLVE_MESSAGES,
        {"plan_published", "lemma_published", "evidence_available", "progress_shared", "conflict_escalated"},
    ),
    ("AlternativeSolver", "solve_new_branch"): _permission(
        _VERIFY_READ,
        {"ProgressArtifact", "CandidateArtifact", "ToolRequestArtifact", "CheckpointArtifact"},
        _SOLVE_ACTIONS,
        _SOLVE_MESSAGES,
        {"plan_published", "lemma_published", "evidence_available", "progress_shared", "conflict_escalated"},
    ),
    ("PrimarySolver", "peer_review_candidate"): _permission(
        _REVIEW_READ,
        {"PeerReviewArtifact", "ProgressArtifact", "CheckpointArtifact"},
        _actions("PrimarySolver", "peer_review"),
        {"peer_review_published", "progress_shared", "task_abstained"},
        {"candidate_published", "peer_review_requested", "lemma_published", "evidence_available", "progress_shared"},
    ),
    ("AlternativeSolver", "peer_review_candidate"): _permission(
        _REVIEW_READ,
        {"PeerReviewArtifact", "ProgressArtifact", "CheckpointArtifact"},
        _actions("AlternativeSolver", "peer_review"),
        {"peer_review_published", "progress_shared", "task_abstained"},
        {"candidate_published", "peer_review_requested", "lemma_published", "evidence_available", "progress_shared"},
    ),
    ("PrimarySolver", "respond_to_peer_review"): _permission(
        _REVIEW_READ,
        {"RebuttalArtifact", "ProgressArtifact", "CheckpointArtifact"},
        _actions("PrimarySolver", "rebuttal"),
        {"rebuttal_published", "progress_shared", "task_abstained"},
        {"peer_review_published", "lemma_published", "evidence_available", "progress_shared"},
    ),
    ("AlternativeSolver", "respond_to_peer_review"): _permission(
        _REVIEW_READ,
        {"RebuttalArtifact", "ProgressArtifact", "CheckpointArtifact"},
        _actions("AlternativeSolver", "rebuttal"),
        {"rebuttal_published", "progress_shared", "task_abstained"},
        {"peer_review_published", "lemma_published", "evidence_available", "progress_shared"},
    ),
    ("LemmaCurator", "curate_lemmas"): _permission(
        _SOLVER_PUBLIC_READ,
        {"LemmaArtifact", "ProgressArtifact", "CheckpointArtifact"},
        _actions("LemmaCurator", "lemma"),
        {"lemma_published", "progress_shared", "task_abstained"},
        {"lemma_requested", "progress_shared"},
    ),
    ("LemmaCurator", "answer_lemma_request"): _permission(
        _SOLVER_PUBLIC_READ,
        {"LemmaArtifact", "ProgressArtifact", "CheckpointArtifact"},
        _actions("LemmaCurator", "lemma"),
        {"lemma_published", "progress_shared", "task_abstained"},
        {"lemma_requested", "progress_shared"},
    ),
    ("VerifierSkeptic", "cross_exam_candidates"): _permission(
        _VERIFY_READ,
        {"PeerReviewArtifact", "CritiqueArtifact", "ProgressArtifact", "CheckpointArtifact"},
        _actions("VerifierSkeptic", "verifier"),
        {"conflict_escalated", "tool_check_requested", "replan_requested", "repair_requested", "progress_shared", "task_abstained"},
        {"candidate_published", "peer_review_published", "rebuttal_published", "evidence_available", "progress_shared"},
    ),
    ("VerifierSkeptic", "final_audit"): _permission(
        _VERIFY_READ | {"AuditArtifact", "DecisionArtifact"},
        {"AuditArtifact", "ProgressArtifact", "CheckpointArtifact"},
        _actions("VerifierSkeptic", "final_audit"),
        {"audit_published", "replan_requested", "repair_requested", "progress_shared", "task_abstained"},
        {"candidate_published", "repair_published", "evidence_available", "audit_requested", "progress_shared"},
    ),
    ("RepairAgent", "repair_claims"): _permission(
        _VERIFY_READ,
        {"RepairPatchArtifact", "RepairResultArtifact", "CandidateArtifact", "ProgressArtifact", "CheckpointArtifact"},
        _actions("RepairAgent", "repair"),
        {"repair_published", "tool_check_requested", "progress_shared", "task_abstained"},
        {"repair_requested", "evidence_available", "progress_shared"},
    ),
    ("LLMFinalizer", "copy_finalize"): _permission(
        _VERIFY_READ | {"AuditArtifact", "DecisionArtifact"},
        {"DecisionArtifact", "CandidateArtifact", "ProgressArtifact", "CheckpointArtifact"},
        _actions("LLMFinalizer", "finalize"),
        {"audit_published", "progress_shared", "task_abstained"},
        {"audit_published", "progress_shared"},
    ),
}


def permission_for(role: str, task_type: str) -> PhasePermission:
    if task_type not in TASK_TYPES:
        raise KeyError(f"unknown Agent task phase: {task_type}")
    try:
        return _PERMISSIONS[(str(role), str(task_type))]
    except KeyError as error:
        raise PermissionError(
            f"{role} has no permission profile for phase {task_type}"
        ) from error


def permissions_for_role(role: str) -> tuple[PhasePermission, ...]:
    return tuple(
        permission
        for (permission_role, _), permission in _PERMISSIONS.items()
        if permission_role == role
    )


def _validate_action_registry_alignment() -> None:
    """Fail at import time if a phase authorizes an undeclared role action."""

    _ACTION_REGISTRY.validate()
    for (role, task_type), permission in _PERMISSIONS.items():
        declared = _ACTION_REGISTRY.actions_for(role)
        if not permission.allowed_action_types <= declared:
            missing = sorted(permission.allowed_action_types - declared)
            raise ValueError(
                f"{role}/{task_type} authorizes undeclared Actions: {missing}"
            )


_validate_action_registry_alignment()
