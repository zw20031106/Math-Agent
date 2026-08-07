from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re
from typing import Any

from mathforge.harness.schemas import MethodFamily, ProblemIR, RoutePlan


ROUTER_PROTOCOL_VERSION = "1.0"
_NODE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_ROLE_TASKS = {
    "PrimarySolver": "solve_primary",
    "AlternativeSolver": "solve_alternative",
    "LemmaCurator": "curate_lemmas",
    "VerifierSkeptic": "cross_exam_candidates",
}


@dataclass(frozen=True)
class SubgoalSpec:
    subgoal_id: str
    objective: str
    depends_on: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentTaskProposal:
    proposal_id: str
    agent_role: str
    task_type: str
    subgoal_ids: tuple[str, ...]
    method_family: str
    priority: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AuthoritativePlan:
    plan_id: str
    version: int
    parent_plan_id: str
    route: dict[str, Any]
    subgoals: tuple[SubgoalSpec, ...]
    task_proposals: tuple[AgentTaskProposal, ...]
    original_condition_digest: str
    preserved_conditions: tuple[str, ...]
    verified_fact_ids: tuple[str, ...]
    source: str
    fallback_reason: str = ""
    schema_version: str = ROUTER_PROTOCOL_VERSION

    def validate(self) -> None:
        if self.schema_version != ROUTER_PROTOCOL_VERSION:
            raise ValueError("invalid authoritative plan schema version")
        if self.version < 1 or not self.plan_id:
            raise ValueError("authoritative plan identity is invalid")
        if self.source not in {"llm_router", "router_rule_fallback"}:
            raise ValueError("authoritative plan source is invalid")
        route = RoutePlan.from_dict(self.route)
        methods = set(route.method_families)
        if not self.subgoals:
            raise ValueError("authoritative plan requires subgoals")
        node_ids = [node.subgoal_id for node in self.subgoals]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("subgoal ids must be unique")
        known = set(node_ids)
        dependencies: dict[str, tuple[str, ...]] = {}
        for node in self.subgoals:
            if not _NODE_ID.fullmatch(node.subgoal_id) or not node.objective.strip():
                raise ValueError("subgoal fields are invalid")
            if node.subgoal_id in node.depends_on or not set(node.depends_on) <= known:
                raise ValueError("subgoal dependency is invalid")
            dependencies[node.subgoal_id] = node.depends_on
        _validate_acyclic(dependencies)
        if not self.task_proposals:
            raise ValueError("authoritative plan requires task proposals")
        proposal_ids: set[str] = set()
        for proposal in self.task_proposals:
            if (
                not _NODE_ID.fullmatch(proposal.proposal_id)
                or proposal.proposal_id in proposal_ids
                or _ROLE_TASKS.get(proposal.agent_role) != proposal.task_type
                or not proposal.subgoal_ids
                or not set(proposal.subgoal_ids) <= known
                or proposal.method_family not in methods
                or not 1 <= proposal.priority <= 100
            ):
                raise ValueError("Agent task proposal is invalid")
            proposal_ids.add(proposal.proposal_id)
        if self.task_proposals[0].agent_role != "PrimarySolver":
            raise ValueError("first task proposal must assign PrimarySolver")
        alternative_count = sum(
            proposal.agent_role == "AlternativeSolver"
            for proposal in self.task_proposals
        )
        if alternative_count < route.candidate_count - 1:
            raise ValueError("Router plan omits required AlternativeSolver tasks")
        if not re.fullmatch(r"[0-9a-f]{64}", self.original_condition_digest):
            raise ValueError("original condition digest is invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "version": self.version,
            "parent_plan_id": self.parent_plan_id,
            "route": dict(self.route),
            "subgoals": [node.to_dict() for node in self.subgoals],
            "task_proposals": [proposal.to_dict() for proposal in self.task_proposals],
            "original_condition_digest": self.original_condition_digest,
            "preserved_conditions": list(self.preserved_conditions),
            "verified_fact_ids": list(self.verified_fact_ids),
            "source": self.source,
            "fallback_reason": self.fallback_reason,
        }


@dataclass(frozen=True)
class RouterPlanningOutcome:
    route_plan: RoutePlan
    authoritative_plan: AuthoritativePlan
    llm_attempted: bool
    source: str
    fallback_reason: str = ""


def build_authoritative_plan(
    problem: ProblemIR,
    route: RoutePlan,
    payload: dict[str, Any] | None,
    *,
    source: str,
    fallback_reason: str = "",
    previous: AuthoritativePlan | None = None,
    verified_fact_ids: tuple[str, ...] = (),
) -> AuthoritativePlan:
    conditions = _preserved_conditions(problem)
    condition_digest = _condition_digest(problem, conditions)
    if previous is not None:
        if previous.original_condition_digest != condition_digest:
            raise ValueError("replan cannot change original conditions")
        conditions = previous.preserved_conditions
        verified_fact_ids = tuple(
            dict.fromkeys((*previous.verified_fact_ids, *verified_fact_ids))
        )
    if payload is None:
        subgoals = _fallback_subgoals(problem)
        proposals = _fallback_task_proposals(route, subgoals)
    else:
        subgoals = _parse_subgoals(payload.get("subgoals"))
        proposals = _parse_task_proposals(payload.get("task_proposals"))
    version = 1 if previous is None else previous.version + 1
    parent_plan_id = "" if previous is None else previous.plan_id
    identity_payload = {
        "version": version,
        "parent_plan_id": parent_plan_id,
        "route": route.to_dict(),
        "subgoals": [item.to_dict() for item in subgoals],
        "task_proposals": [item.to_dict() for item in proposals],
        "original_condition_digest": condition_digest,
        "verified_fact_ids": list(verified_fact_ids),
        "source": source,
    }
    digest = sha256(
        json.dumps(
            identity_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    plan = AuthoritativePlan(
        plan_id=f"plan-v{version}-{digest[:16]}",
        version=version,
        parent_plan_id=parent_plan_id,
        route=route.to_dict(),
        subgoals=subgoals,
        task_proposals=proposals,
        original_condition_digest=condition_digest,
        preserved_conditions=conditions,
        verified_fact_ids=verified_fact_ids,
        source=source,
        fallback_reason=str(fallback_reason),
    )
    plan.validate()
    return plan


def valid_method_families(value: Any) -> list[str]:
    if not isinstance(value, list) or not value or len(value) > 3:
        raise ValueError("Router method_families must contain one to three values")
    methods = [str(item) for item in value]
    allowed = {item.value for item in MethodFamily}
    if len(methods) != len(set(methods)) or not set(methods) <= allowed:
        raise ValueError("Router selected an invalid method family")
    return methods


def _parse_subgoals(value: Any) -> tuple[SubgoalSpec, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= 12:
        raise ValueError("Router subgoals must be a non-empty bounded list")
    result: list[SubgoalSpec] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"subgoal_id", "objective", "depends_on"}:
            raise ValueError("Router subgoal schema is invalid")
        dependencies = item["depends_on"]
        if not isinstance(dependencies, list) or any(not isinstance(dep, str) for dep in dependencies):
            raise ValueError("Router subgoal dependencies are invalid")
        result.append(
            SubgoalSpec(
                str(item["subgoal_id"]),
                str(item["objective"]),
                tuple(dependencies),
            )
        )
    return tuple(result)


def _parse_task_proposals(value: Any) -> tuple[AgentTaskProposal, ...]:
    required = {
        "proposal_id",
        "agent_role",
        "task_type",
        "subgoal_ids",
        "method_family",
        "priority",
    }
    if not isinstance(value, list) or not 1 <= len(value) <= 12:
        raise ValueError("Router task proposals must be a non-empty bounded list")
    result: list[AgentTaskProposal] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != required:
            raise ValueError("Router task proposal schema is invalid")
        subgoal_ids = item["subgoal_ids"]
        if not isinstance(subgoal_ids, list) or any(not isinstance(node, str) for node in subgoal_ids):
            raise ValueError("Router task proposal subgoals are invalid")
        priority = item["priority"]
        if type(priority) is not int:
            raise ValueError("Router task proposal priority is invalid")
        result.append(
            AgentTaskProposal(
                str(item["proposal_id"]),
                str(item["agent_role"]),
                str(item["task_type"]),
                tuple(subgoal_ids),
                str(item["method_family"]),
                priority,
            )
        )
    return tuple(result)


def _fallback_subgoals(problem: ProblemIR) -> tuple[SubgoalSpec, ...]:
    objectives = [item for item in problem.subproblem_hints if item.strip()][:6]
    if not objectives:
        objectives = [problem.target_phrase or problem.requested_output or "Solve the stated mathematical target"]
    return tuple(
        SubgoalSpec(
            f"sg-{index}",
            objective,
            (f"sg-{index - 1}",) if index > 1 else (),
        )
        for index, objective in enumerate(objectives, start=1)
    )


def _fallback_task_proposals(route: RoutePlan, subgoals: tuple[SubgoalSpec, ...]) -> tuple[AgentTaskProposal, ...]:
    methods = route.method_families or [MethodFamily.DIRECT_DEDUCTION.value]
    proposals = [
        AgentTaskProposal(
            "proposal-primary",
            "PrimarySolver",
            "solve_primary",
            tuple(node.subgoal_id for node in subgoals),
            methods[0],
            100,
        )
    ]
    for index, method in enumerate(methods[1 : route.candidate_count], start=1):
        proposals.append(
            AgentTaskProposal(
                f"proposal-alternative-{index}",
                "AlternativeSolver",
                "solve_alternative",
                tuple(node.subgoal_id for node in subgoals),
                method,
                80 - index,
            )
        )
    return tuple(proposals)


def _preserved_conditions(problem: ProblemIR) -> tuple[str, ...]:
    values = (
        *problem.assumptions,
        *problem.definitions,
        *problem.quantifiers,
        *problem.constraints,
    )
    return tuple(dict.fromkeys(item.strip() for item in values if item.strip()))


def _condition_digest(problem: ProblemIR, conditions: tuple[str, ...]) -> str:
    payload = {
        "normalized_problem": problem.normalized_problem,
        "problem_type": problem.problem_type,
        "answer_type": problem.answer_type,
        "response_mode": problem.response_mode,
        "target_phrase": problem.target_phrase,
        "target_kind": problem.target_kind,
        "conditions": list(conditions),
    }
    return sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _validate_acyclic(dependencies: dict[str, tuple[str, ...]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise ValueError("subgoal DAG contains a cycle")
        if node in visited:
            return
        visiting.add(node)
        for dependency in dependencies[node]:
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in dependencies:
        visit(node)
