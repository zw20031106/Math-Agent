from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from hashlib import sha256
import json

from mathforge.agent_runtime.definitions import AgentRegistry
from mathforge.agent_runtime.router_protocol import AgentTaskProposal, AuthoritativePlan


EXECUTION_PLAN_VERSION = "1.0"


@dataclass(frozen=True)
class HostAdmittedPlan:
    plan_id: str
    plan_version: int
    router_plan_id: str
    admitted_tasks: tuple[AgentTaskProposal, ...]
    rejected_proposal_ids: tuple[str, ...]
    admission_reasons: tuple[str, ...]
    schema_version: str = EXECUTION_PLAN_VERSION

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "admitted_tasks": [item.to_dict() for item in self.admitted_tasks],
            "rejected_proposal_ids": list(self.rejected_proposal_ids),
            "admission_reasons": list(self.admission_reasons),
        }


@dataclass(frozen=True)
class EffectiveBranch:
    branch_id: str
    agent_role: str
    task_type: str
    subgoal_ids: tuple[str, ...]
    method_family: str
    plan_id: str
    plan_version: int
    shared_context_hash: str = ""
    branch_context_hash: str = ""

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["subgoal_ids"] = list(self.subgoal_ids)
        return payload


@dataclass(frozen=True)
class EffectiveExecutionPlan:
    plan_id: str
    version: int
    parent_plan_id: str
    router_plan_id: str
    branches: tuple[EffectiveBranch, ...]
    shared_lemma_policy: str
    schema_version: str = EXECUTION_PLAN_VERSION

    @property
    def solver_branches(self) -> tuple[EffectiveBranch, ...]:
        return tuple(
            branch
            for branch in self.branches
            if branch.agent_role in {"PrimarySolver", "AlternativeSolver"}
        )

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "version": self.version,
            "parent_plan_id": self.parent_plan_id,
            "router_plan_id": self.router_plan_id,
            "branches": [item.to_dict() for item in self.branches],
            "shared_lemma_policy": self.shared_lemma_policy,
        }


@dataclass
class ReplanBarrier:
    from_version: int
    to_version: int
    required_agent_ids: tuple[str, ...]
    acknowledged_agent_ids: set[str] = field(default_factory=set)
    status: str = "paused"

    def acknowledge(self, agent_id: str, version: int) -> None:
        if self.status != "paused" or version != self.to_version:
            raise ValueError("replan acknowledgement version is inconsistent")
        if agent_id not in self.required_agent_ids:
            raise ValueError("replan acknowledgement Agent is not required")
        self.acknowledged_agent_ids.add(agent_id)

    def resume(self) -> None:
        if set(self.required_agent_ids) != self.acknowledged_agent_ids:
            raise RuntimeError("replan barrier cannot resume before every ACK")
        self.status = "resumed"

    def to_dict(self) -> dict:
        return {
            "from_version": self.from_version,
            "to_version": self.to_version,
            "required_agent_ids": list(self.required_agent_ids),
            "acknowledged_agent_ids": sorted(self.acknowledged_agent_ids),
            "status": self.status,
        }


@dataclass(frozen=True)
class BranchPlanOverride:
    branch_id: str
    base_plan_id: str
    base_plan_version: int
    override_version: int
    method_family: str
    reason: str

    def validate_against(self, effective: EffectiveExecutionPlan) -> None:
        if self.base_plan_id != effective.plan_id or self.base_plan_version != effective.version:
            raise ValueError("BranchPlanOverride base plan is stale")
        if self.override_version < 1 or not self.method_family or not self.reason:
            raise ValueError("BranchPlanOverride is incomplete")
        if self.branch_id not in {item.branch_id for item in effective.branches}:
            raise ValueError("BranchPlanOverride branch is unknown")


def admit_router_plan(
    plan: AuthoritativePlan,
    agents: AgentRegistry,
    *,
    candidate_limit: int | None = None,
) -> HostAdmittedPlan:
    admitted: list[AgentTaskProposal] = []
    rejected: list[str] = []
    reasons: list[str] = []
    admitted_solver_count = 0
    for proposal in plan.task_proposals:
        try:
            definition = agents.get(proposal.agent_role)
        except KeyError:
            rejected.append(proposal.proposal_id)
            reasons.append(f"{proposal.proposal_id}:unknown_role")
            continue
        if proposal.task_type not in definition.accepted_task_types:
            rejected.append(proposal.proposal_id)
            reasons.append(f"{proposal.proposal_id}:task_not_permitted")
            continue
        if proposal.agent_role in {"PrimarySolver", "AlternativeSolver"}:
            if candidate_limit is not None and admitted_solver_count >= candidate_limit:
                rejected.append(proposal.proposal_id)
                reasons.append(f"{proposal.proposal_id}:host_candidate_limit")
                continue
            admitted_solver_count += 1
        admitted.append(proposal)
    roles = {item.agent_role for item in admitted}
    if "PrimarySolver" not in roles:
        raise ValueError("Host admission requires a PrimarySolver branch")
    if (candidate_limit is None or candidate_limit > 1) and "AlternativeSolver" not in roles:
        raise ValueError("Host admission requires an AlternativeSolver branch")
    return HostAdmittedPlan(
        plan_id=f"host-{plan.plan_id}",
        plan_version=plan.version,
        router_plan_id=plan.plan_id,
        admitted_tasks=tuple(admitted),
        rejected_proposal_ids=tuple(rejected),
        admission_reasons=tuple(reasons),
    )


def build_effective_execution_plan(
    plan: AuthoritativePlan,
    admitted: HostAdmittedPlan,
) -> EffectiveExecutionPlan:
    branches: list[EffectiveBranch] = []
    role_ordinals: dict[str, int] = {}
    for proposal in admitted.admitted_tasks:
        ordinal = role_ordinals.get(proposal.agent_role, 0) + 1
        role_ordinals[proposal.agent_role] = ordinal
        branch_id = f"{proposal.agent_role.casefold()}-{ordinal}"
        branches.append(
            EffectiveBranch(
                branch_id,
                proposal.agent_role,
                proposal.task_type,
                proposal.subgoal_ids,
                proposal.method_family,
                plan.plan_id,
                plan.version,
            )
        )
    identity = sha256(
        json.dumps(
            [item.to_dict() for item in branches],
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return EffectiveExecutionPlan(
        plan_id=f"effective-v{plan.version}-{identity[:16]}",
        version=plan.version,
        parent_plan_id=plan.parent_plan_id,
        router_plan_id=plan.plan_id,
        branches=tuple(branches),
        shared_lemma_policy="off_until_candidate_backbone",
    )


def bind_execution_context_hashes(
    effective: EffectiveExecutionPlan,
    *,
    shared_context: dict,
    branch_contexts: dict[str, dict],
) -> EffectiveExecutionPlan:
    """Bind hashes to the exact public context payloads dispatched to branches."""

    branch_ids = {item.branch_id for item in effective.branches}
    if set(branch_contexts) != branch_ids:
        raise ValueError("branch context payloads must cover the effective plan exactly")
    shared_hash = _context_hash(shared_context)
    return replace(
        effective,
        branches=tuple(
            replace(
                branch,
                shared_context_hash=shared_hash,
                branch_context_hash=_context_hash(branch_contexts[branch.branch_id]),
            )
            for branch in effective.branches
        ),
    )


def _context_hash(payload: dict) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()
