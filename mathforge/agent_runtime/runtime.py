from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import re
from threading import RLock
from typing import Any

from mathforge.agent_runtime.action_registry import ActionRegistry
from mathforge.agent_runtime.artifact_store import SessionArtifactStore
from mathforge.agent_runtime.definitions import AgentRegistry
from mathforge.agent_runtime.mailbox import SessionMailbox
from mathforge.agent_runtime.protocol import AgentTurnPayload, AgentTurnPayloadParser, PROTOCOL_SCHEMA_VERSION, TurnContext, TurnLineage
from mathforge.agent_runtime.router_protocol import AuthoritativePlan
from mathforge.agent_runtime.execution_plan import (
    EffectiveExecutionPlan,
    ReplanBarrier,
    admit_router_plan,
    bind_execution_context_hashes,
    build_effective_execution_plan,
)
from mathforge.agent_runtime.permissions import permission_for
from mathforge.agent_runtime.state import AgentInstance, AgentStateRegistry, AgentTaskRegistry, TERMINAL_AGENT_STATES
from mathforge.harness.cancellation import CancellationToken


_ROLE_BY_STAGE = {
    "router": "RouterPlanner", "primary": "PrimarySolver", "alternative": "AlternativeSolver",
    "lemma": "LemmaCurator", "verifier": "VerifierSkeptic", "repair": "RepairAgent", "finalizer": "LLMFinalizer",
}
_COMPATIBLE_ROLES_BY_STAGE = {
    # Verified-lemma expansion is a solver-owned turn using the lemma budget
    # bucket, while direct lemma curation remains owned by LemmaCurator.
    "lemma": frozenset({"LemmaCurator", "PrimarySolver", "AlternativeSolver"}),
}
_MODE_BY_ROLE = {
    "RouterPlanner": "plan", "PrimarySolver": "solve", "AlternativeSolver": "solve",
    "LemmaCurator": "curate", "VerifierSkeptic": "cross_exam", "RepairAgent": "repair", "LLMFinalizer": "finalize",
}
_TASK_BY_ROLE = {
    "RouterPlanner": "route_and_plan", "PrimarySolver": "solve_primary", "AlternativeSolver": "solve_alternative",
    "LemmaCurator": "curate_lemmas", "VerifierSkeptic": "cross_exam_candidates", "RepairAgent": "repair_claims", "LLMFinalizer": "copy_finalize",
}
_TURN_KINDS_BY_ROLE = {
    "RouterPlanner": frozenset({"router", "replan"}),
    "PrimarySolver": frozenset(
        {
            "primary",
            "solver_progress",
            "solver_candidate_standard",
            "solver_candidate_proof",
            "solver_compact_synthesis",
            "replacement_compact_candidate",
            "emergency_direct_answer",
            "lemma_curator",
            "peer_review",
        }
    ),
    "AlternativeSolver": frozenset(
        {
            "alternative",
            "solver_progress",
            "solver_candidate_standard",
            "solver_candidate_proof",
            "solver_compact_synthesis",
            "replacement_compact_candidate",
            "lemma_curator",
            "peer_review",
        }
    ),
    "LemmaCurator": frozenset({"lemma", "lemma_curator"}),
    "VerifierSkeptic": frozenset({"verifier", "peer_review", "final_audit"}),
    "RepairAgent": frozenset({"repair"}),
    "LLMFinalizer": frozenset({"finalizer"}),
}
_OUTPUT_BY_ROLE = {
    "RouterPlanner": ("PlanArtifact", "plan_published", "PrimarySolver"),
    "PrimarySolver": ("CandidateArtifact", "candidate_published", "VerifierSkeptic"),
    "AlternativeSolver": ("CandidateArtifact", "candidate_published", "VerifierSkeptic"),
    "LemmaCurator": ("LemmaArtifact", "lemma_published", "PrimarySolver"),
    "VerifierSkeptic": ("CritiqueArtifact", "peer_review_published", "PrimarySolver"),
    "RepairAgent": ("RepairPatchArtifact", "repair_published", "VerifierSkeptic"),
    "LLMFinalizer": ("DecisionArtifact", "audit_published", "PrimarySolver"),
}


class SessionAgentRuntime:
    """Per-solve protocol runtime with an authoritative Router boundary."""

    def __init__(self, session_id: str, definitions: AgentRegistry) -> None:
        self.session_id = session_id
        self.definitions = definitions
        self.agents = AgentStateRegistry(session_id, definitions)
        self.tasks = AgentTaskRegistry(session_id, self.agents, definitions)
        self.artifacts = SessionArtifactStore(session_id, self.agents, definitions)
        self.mailbox = SessionMailbox(session_id, self.agents, self.tasks, self.artifacts, definitions)
        self._agent_keys: dict[tuple[str, str], str] = {}
        self._task_keys: dict[tuple[str, str, str], str] = {}
        self._thread_keys: dict[tuple[str, str], str] = {}
        self._turns: dict[str, TurnLineage] = {}
        self._turn_contexts: dict[str, TurnContext] = {}
        self._review_thread_by_artifact: dict[str, str] = {}
        self._sequence = 0
        self._authoritative_plan: AuthoritativePlan | None = None
        self._effective_execution_plan: EffectiveExecutionPlan | None = None
        self._host_admitted_plan = None
        self._replan_barrier: ReplanBarrier | None = None
        self._plan_artifact_by_version: dict[int, str] = {}
        self._protocol_event_sequence = 0
        self._protocol_events: list[dict[str, Any]] = []
        self._actions = ActionRegistry()
        self._agent_action_turns = False
        self._cancellation_token: CancellationToken | None = None
        self._released = False
        self._lock = RLock()

    def _record_protocol_event(self, event_type: str, **details: Any) -> None:
        self._protocol_event_sequence += 1
        self._protocol_events.append(
            {
                "sequence": self._protocol_event_sequence,
                "event_type": str(event_type),
                **details,
            }
        )

    def bind_cancellation_token(self, token: CancellationToken) -> None:
        with self._lock:
            if self._cancellation_token not in {None, token}:
                raise RuntimeError("cancellation token is already bound")
            self._cancellation_token = token

    def bind_authoritative_plan(
        self,
        plan: AuthoritativePlan,
        *,
        candidate_limit: int | None = None,
    ) -> None:
        with self._lock:
            plan.validate()
            if self._authoritative_plan is not None:
                if plan.version <= self._authoritative_plan.version:
                    raise ValueError("authoritative plan version must increase")
                if plan.parent_plan_id != self._authoritative_plan.plan_id:
                    raise ValueError("authoritative replan parent is invalid")
                if (
                    plan.original_condition_digest
                    != self._authoritative_plan.original_condition_digest
                ):
                    raise ValueError("authoritative replan changed original conditions")
            previous_version = (
                self._effective_execution_plan.version
                if self._effective_execution_plan is not None
                else 0
            )
            admitted = admit_router_plan(
                plan,
                self.definitions,
                candidate_limit=candidate_limit,
            )
            effective = build_effective_execution_plan(plan, admitted)
            if previous_version:
                required = tuple(
                    item["agent_id"]
                    for item in self.agents.snapshot()
                    if item["role"] in {"PrimarySolver", "AlternativeSolver"}
                )
                self._replan_barrier = ReplanBarrier(
                    previous_version,
                    effective.version,
                    required,
                )
            self._authoritative_plan = plan
            self._host_admitted_plan = admitted
            self._effective_execution_plan = effective

    @property
    def effective_execution_plan(self) -> EffectiveExecutionPlan:
        if self._effective_execution_plan is None:
            raise RuntimeError("EffectiveExecutionPlan is not bound")
        return self._effective_execution_plan

    def bind_execution_contexts(
        self,
        *,
        shared_context: dict[str, Any],
        branch_contexts: dict[str, dict[str, Any]],
    ) -> EffectiveExecutionPlan:
        with self._lock:
            self._ensure_active()
            self._effective_execution_plan = bind_execution_context_hashes(
                self.effective_execution_plan,
                shared_context=shared_context,
                branch_contexts=branch_contexts,
            )
            return self._effective_execution_plan

    def acknowledge_replan(self, agent_id: str, version: int) -> None:
        with self._lock:
            if self._replan_barrier is None:
                raise RuntimeError("no replan barrier is active")
            self._replan_barrier.acknowledge(agent_id, version)
            self._record_protocol_event(
                "replan_acknowledged",
                agent_id=agent_id,
                plan_version=version,
            )

    def resume_replan(self) -> None:
        with self._lock:
            if self._replan_barrier is None:
                raise RuntimeError("no replan barrier is active")
            self._replan_barrier.resume()
            self._record_protocol_event(
                "replan_resumed",
                plan_version=self._replan_barrier.to_version,
            )

    @property
    def replan_barrier(self) -> dict[str, Any] | None:
        return self._replan_barrier.to_dict() if self._replan_barrier else None

    def publish_router_decision(
        self,
        *,
        route_payload: dict[str, Any],
        plan: AuthoritativePlan,
        candidate_limit: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._ensure_active()
            self.bind_authoritative_plan(plan, candidate_limit=candidate_limit)
            router_context = next(
                (
                    context
                    for context in reversed(tuple(self._turn_contexts.values()))
                    if context.role == "RouterPlanner"
                ),
                None,
            )
            if router_context is None:
                router = self._ensure_agent("RouterPlanner", "fallback")
                task = self.tasks.create("route_and_plan", router.agent_id)
                self._record_protocol_event(
                    "task_assigned",
                    task_id=task.task_id,
                    task_type=task.task_type,
                    agent_id=router.agent_id,
                )
                self._sequence += 1
                router_context = TurnContext(
                    router.agent_id,
                    router.role,
                    router.mode,
                    task.task_id,
                    task.task_type,
                    f"turn-{self.session_id[:8]}-{self._sequence:04d}-fallback",
                    "router_fallback",
                    "PlanArtifact",
                    "plan_published",
                    "PrimarySolver",
                )
            previous = self.tasks.get(router_context.task_id).output_artifact_ids
            route_artifact = self.artifacts.publish(
                artifact_type="RouteArtifact",
                producer_agent_id=router_context.agent_id,
                task_id=router_context.task_id,
                turn_id=router_context.turn_id,
                payload={
                    "route": dict(route_payload),
                    "plan_id": plan.plan_id,
                    "source": plan.source,
                    "fallback_reason": plan.fallback_reason,
                },
                parent_artifact_ids=(previous[-1],) if previous else (),
            )
            plan_artifact = self.artifacts.publish(
                artifact_type="PlanArtifact",
                producer_agent_id=router_context.agent_id,
                task_id=router_context.task_id,
                turn_id=router_context.turn_id,
                payload={
                    "router_plan": plan.to_dict(),
                    "host_admitted_plan": self._host_admitted_plan.to_dict(),
                    "effective_execution_plan": (
                        self.effective_execution_plan.to_dict()
                    ),
                },
                parent_artifact_ids=(route_artifact.artifact_id,),
            )
            self._plan_artifact_by_version[plan.version] = plan_artifact.artifact_id
            for artifact in (route_artifact, plan_artifact):
                self.tasks.append_output(router_context.task_id, artifact.artifact_id)
                self.agents.append(
                    router_context.agent_id,
                    "output_artifact_ids",
                    artifact.artifact_id,
                )
                self._record_protocol_event(
                    "artifact_published",
                    artifact_id=artifact.artifact_id,
                    artifact_type=artifact.artifact_type,
                    producer_agent_id=artifact.producer_agent_id,
                    task_id=artifact.task_id,
                    turn_id=artifact.turn_id,
                )
            recipients: list[AgentInstance] = []
            role_ordinals: dict[str, int] = {}
            for branch in self.effective_execution_plan.solver_branches:
                ordinal = role_ordinals.get(branch.agent_role, 0) + 1
                role_ordinals[branch.agent_role] = ordinal
                descriptor = (
                    f"primary-{ordinal}"
                    if branch.agent_role == "PrimarySolver"
                    else f"alternative-{ordinal}"
                )
                recipients.append(self._ensure_agent(branch.agent_role, descriptor))
            if self._replan_barrier is not None:
                known = {item.agent_id for item in recipients}
                recipients.extend(
                    self.agents.instance(agent_id)
                    for agent_id in self._replan_barrier.required_agent_ids
                    if agent_id not in known
                )
            messages = []
            for recipient in recipients:
                pair = tuple(sorted((router_context.agent_id, recipient.agent_id)))
                thread_id = self._thread_keys.get(pair)
                if not thread_id:
                    thread_id = self.mailbox.create_thread(
                        (router_context.agent_id, recipient.agent_id)
                    ).thread_id
                    self._thread_keys[pair] = thread_id
                message = self.mailbox.send(
                    thread_id=thread_id,
                    sender_agent_id=router_context.agent_id,
                    recipient_agent_id=recipient.agent_id,
                    task_id=router_context.task_id,
                    message_type="plan_published",
                    artifact_ids=(
                        route_artifact.artifact_id,
                        plan_artifact.artifact_id,
                    ),
                    public_summary=(
                        f"Router published authoritative plan {plan.plan_id} "
                        f"from {plan.source}"
                    ),
                    reply_to_message_id=self.mailbox.latest_message_id(thread_id),
                )
                messages.append(message)
                self._record_protocol_event(
                    "message_sent",
                    message_id=message.message_id,
                    thread_id=message.thread_id,
                    sender_agent_id=message.sender_agent_id,
                    recipient_agent_id=message.recipient_agent_id,
                    message_type=message.message_type,
                    artifact_ids=list(message.artifact_ids),
                )
            return {
                "route_artifact_id": route_artifact.artifact_id,
                "plan_artifact_id": plan_artifact.artifact_id,
                "plan_message_id": messages[0].message_id,
                "plan_message_ids": [item.message_id for item in messages],
                "effective_plan_id": self.effective_execution_plan.plan_id,
                "effective_plan_version": self.effective_execution_plan.version,
                "host_admitted_plan_id": self._host_admitted_plan.plan_id,
                "host_rejected_proposal_ids": list(
                    self._host_admitted_plan.rejected_proposal_ids
                ),
                "effective_branch_ids": [
                    item.branch_id
                    for item in self.effective_execution_plan.branches
                ],
                "shared_lemma_policy": (
                    self.effective_execution_plan.shared_lemma_policy
                ),
            }

    def _ensure_agent(
        self,
        role: str,
        descriptor: str = "default",
        *,
        mode: str | None = None,
    ) -> AgentInstance:
        self._ensure_active()
        key = (role, descriptor)
        agent_id = self._agent_keys.get(key)
        if agent_id:
            return self.agents.instance(agent_id)
        active_mode = mode or _MODE_BY_ROLE[role]
        if active_mode not in self.definitions.get(role).allowed_modes:
            raise ValueError("Agent mode is not allowed for this role")
        ordinal = 1 + sum(1 for item in self._agent_keys if item[0] == role)
        agent_id = f"{self.session_id}:{role}:{active_mode}:{ordinal}"
        instance = AgentInstance(
            agent_id,
            self.session_id,
            role,
            active_mode,
            descriptor,
        )
        self.agents.create(instance)
        self._agent_keys[key] = agent_id
        self._record_protocol_event(
            "agent_created",
            agent_id=instance.agent_id,
            role=instance.role,
            mode=instance.mode,
            descriptor=instance.descriptor,
        )
        return instance

    def agent_id_for(self, role: str, descriptor: str) -> str:
        with self._lock:
            try:
                return self._agent_keys[(str(role), str(descriptor))]
            except KeyError as error:
                raise KeyError("Agent identity is not active in this session") from error

    def begin_model_turn(
        self,
        *,
        stage: str,
        turn_kind: str,
        agent_hint: str = "",
        input_artifact_ids: tuple[str, ...] = (),
    ) -> TurnContext:
        with self._lock:
            if self._released:
                raise RuntimeError("Agent runtime has been released")
            self._ensure_active()
            normalized_stage = str(stage).strip()
            normalized_hint = str(agent_hint).strip()
            hinted_role = normalized_hint.split(":", 1)[0]
            known_roles = set(self.definitions.roles())
            if normalized_hint and hinted_role not in known_roles:
                raise ValueError(f"unknown Agent role: {hinted_role}")
            expected_role = _ROLE_BY_STAGE.get(normalized_stage)
            if expected_role is None:
                raise ValueError(f"unknown Agent stage: {normalized_stage}")
            if (
                expected_role
                and hinted_role
                and expected_role != hinted_role
                and hinted_role
                not in _COMPATIBLE_ROLES_BY_STAGE.get(
                    normalized_stage,
                    frozenset({expected_role}),
                )
            ):
                raise ValueError(
                    f"Agent role {hinted_role} is invalid for stage {normalized_stage}"
                )
            role = hinted_role or expected_role
            if role is None or role not in known_roles:
                raise ValueError("Agent role could not be resolved")
            normalized_turn_kind = str(turn_kind).strip()
            if normalized_turn_kind not in _TURN_KINDS_BY_ROLE.get(role, frozenset()):
                raise ValueError(
                    f"invalid task turn kind for {role}: {normalized_turn_kind}"
                )
            if (
                self._replan_barrier is not None
                and self._replan_barrier.status == "paused"
                and role in {"PrimarySolver", "AlternativeSolver"}
            ):
                raise RuntimeError("Solver Turn blocked by replan ACK barrier")
            descriptor = (
                str(agent_hint).split(":", 1)[1]
                if ":" in str(agent_hint)
                else "default"
                if hinted_role in self.definitions.roles()
                else str(turn_kind)
            )
            requested_mode = (
                "final_audit"
                if role == "VerifierSkeptic"
                and str(descriptor).startswith("final-audit")
                else _MODE_BY_ROLE[role]
            )
            pending_recipient_id = self.mailbox.pending_recipient_for_artifacts(
                recipient_role=role,
                artifact_ids=tuple(input_artifact_ids),
            )
            pending_recipient = (
                self.agents.instance(pending_recipient_id)
                if pending_recipient_id
                else None
            )
            instance = (
                pending_recipient
                if pending_recipient is not None
                and pending_recipient.mode == requested_mode
                else self._ensure_agent(
                    role,
                    descriptor or "default",
                    mode=requested_mode,
                )
            )
            if role in {"PrimarySolver", "AlternativeSolver"}:
                self._ensure_current_plan_delivery(instance)
            input_artifact_ids = tuple(
                dict.fromkeys(
                    (
                        *input_artifact_ids,
                        *self.mailbox.pending_artifacts_for_recipient(
                            instance.agent_id,
                            message_types=frozenset({"plan_published"}),
                        ),
                    )
                )
            )
            task_type = _TASK_BY_ROLE[role]
            (
                plan_id,
                plan_version,
                subgoal_ids,
                method_family,
                shared_context_hash,
                branch_context_hash,
            ) = self._task_plan(role, descriptor)
            artifact_type, message_type, recipient_role = _OUTPUT_BY_ROLE[role]
            mode = instance.mode
            recipient_agent_id = ""
            thread_id = ""
            reply_to_message_id = ""
            close_thread_after_publish = False
            if turn_kind == "peer_review" and input_artifact_ids:
                (
                    mode,
                    task_type,
                    artifact_type,
                    message_type,
                    recipient_role,
                    recipient_agent_id,
                    thread_id,
                    reply_to_message_id,
                    close_thread_after_publish,
                ) = self._collaboration_turn_route(
                    instance,
                    input_artifact_ids[0],
                )
            elif role == "VerifierSkeptic":
                if mode == "final_audit":
                    task_type = "final_audit"
                    artifact_type = "AuditArtifact"
                    message_type = "audit_published"
                else:
                    task_type = "cross_exam_candidates"
                    artifact_type = "CritiqueArtifact"
                    message_type = "conflict_escalated"
            elif (
                role in {"PrimarySolver", "AlternativeSolver"}
                and str(descriptor).startswith("new-branch-")
                and input_artifact_ids
            ):
                task_type = "solve_new_branch"
            if mode not in self.definitions.get(role).allowed_modes:
                raise ValueError("Agent collaboration mode is not allowed")
            phase_permission = permission_for(role, task_type)
            input_artifact_ids = tuple(
                dict.fromkeys(
                    (
                        *input_artifact_ids,
                        *self.mailbox.pending_artifacts_for_recipient(
                            instance.agent_id,
                            message_types=phase_permission.accepted_message_types,
                        ),
                    )
                )
            )
            for artifact_id in input_artifact_ids:
                artifact = self.artifacts.get(artifact_id)
                if artifact.artifact_type not in phase_permission.readable_artifact_types:
                    raise PermissionError(
                        f"{role} phase cannot read {artifact.artifact_type}"
                    )
            prior_agent_turn = any(
                item.agent_id == instance.agent_id
                for item in self._turn_contexts.values()
            )
            required_plan_artifact_id = self._plan_artifact_by_version.get(
                plan_version,
                "",
            )
            if (
                role in {"PrimarySolver", "AlternativeSolver"}
                and not prior_agent_turn
                and required_plan_artifact_id
                and required_plan_artifact_id not in input_artifact_ids
            ):
                raise RuntimeError("first Solver Turn must consume PlanArtifact")
            key = (
                instance.agent_id,
                task_type,
                plan_id + ":" + ":".join(input_artifact_ids),
            )
            task_id = self._task_keys.get(key)
            if not task_id:
                task_id = self.tasks.create(
                    task_type,
                    instance.agent_id,
                    plan_id=plan_id,
                    plan_version=plan_version,
                    subgoal_ids=subgoal_ids,
                    method_family=method_family,
                    input_artifact_ids=tuple(input_artifact_ids),
                ).task_id
                self._task_keys[key] = task_id
                task = self.tasks.get(task_id)
                self._record_protocol_event(
                    "task_assigned",
                    task_id=task.task_id,
                    task_type=task.task_type,
                    agent_id=task.assigned_agent_id,
                    plan_id=task.plan_id,
                    plan_version=task.plan_version,
                )
            if turn_kind == "solver_progress":
                artifact_type, message_type, recipient_role = "ProgressArtifact", "progress_shared", "RouterPlanner"
            self._sequence += 1
            turn_id = f"turn-{self.session_id[:8]}-{self._sequence:04d}"
            context = TurnContext(
                instance.agent_id,
                role,
                mode,
                task_id,
                task_type,
                turn_id,
                turn_kind,
                artifact_type,
                message_type,
                recipient_role,
                plan_id,
                subgoal_ids,
                method_family,
                tuple(input_artifact_ids),
                recipient_agent_id,
                thread_id,
                reply_to_message_id,
                close_thread_after_publish,
                plan_version,
                shared_context_hash,
                branch_context_hash,
            )
            self._turn_contexts[turn_id] = context
            self._turns[turn_id] = TurnLineage(instance.agent_id, task_id, turn_id)
            receipts = self.mailbox.consume_for_turn(
                consumer_agent_id=instance.agent_id,
                turn_id=turn_id,
                input_artifact_ids=tuple(input_artifact_ids),
                accepted_message_types=phase_permission.accepted_message_types,
            )
            for receipt in receipts:
                self._record_protocol_event(
                    "message_consumed",
                    receipt_id=receipt.receipt_id,
                    message_id=receipt.message_id,
                    consumer_agent_id=receipt.consumer_agent_id,
                    turn_id=receipt.turn_id,
                    artifact_ids=list(receipt.artifact_ids),
                )
            self._record_protocol_event(
                "model_turn_started",
                turn_id=turn_id,
                agent_id=instance.agent_id,
                task_id=task_id,
                plan_id=plan_id,
                plan_version=plan_version,
            )
            return context

    def _ensure_current_plan_delivery(self, recipient: AgentInstance) -> None:
        plan = self._effective_execution_plan
        if plan is None:
            return
        plan_artifact_id = self._plan_artifact_by_version.get(plan.version, "")
        if not plan_artifact_id:
            return
        if any(
            message["recipient_agent_id"] == recipient.agent_id
            and message["message_type"] == "plan_published"
            and plan_artifact_id in message["artifact_ids"]
            for message in self.mailbox.snapshot()["messages"]
        ):
            return
        plan_artifact = self.artifacts.get(plan_artifact_id)
        route_artifact_ids = tuple(
            artifact_id
            for artifact_id in plan_artifact.parent_artifact_ids
            if self.artifacts.get(artifact_id).artifact_type == "RouteArtifact"
        )
        sender = self.agents.instance(plan_artifact.producer_agent_id)
        pair = tuple(sorted((sender.agent_id, recipient.agent_id)))
        thread_id = self._thread_keys.get(pair)
        if not thread_id:
            thread_id = self.mailbox.create_thread(pair).thread_id
            self._thread_keys[pair] = thread_id
        message = self.mailbox.send(
            thread_id=thread_id,
            sender_agent_id=sender.agent_id,
            recipient_agent_id=recipient.agent_id,
            task_id=plan_artifact.task_id,
            message_type="plan_published",
            artifact_ids=(*route_artifact_ids, plan_artifact_id),
            public_summary=f"Router delivered active plan version {plan.version}",
            reply_to_message_id=self.mailbox.latest_message_id(thread_id),
        )
        self._record_protocol_event(
            "message_sent",
            message_id=message.message_id,
            thread_id=message.thread_id,
            sender_agent_id=message.sender_agent_id,
            recipient_agent_id=message.recipient_agent_id,
            message_type=message.message_type,
            artifact_ids=list(message.artifact_ids),
        )

    def _collaboration_turn_route(
        self,
        instance: AgentInstance,
        input_artifact_id: str,
    ) -> tuple[str, str, str, str, str, str, str, str, bool]:
        source = self.artifacts.get(
            input_artifact_id,
            reader_agent_id=instance.agent_id,
        )
        recipient = self.agents.instance(source.producer_agent_id)
        if source.artifact_type == "CandidateArtifact":
            if instance.role == recipient.role:
                raise ValueError("a Solver cannot peer-review its own Candidate")
            thread = self.mailbox.create_thread(
                (source.producer_agent_id, instance.agent_id)
            )
            request = self.mailbox.send(
                thread_id=thread.thread_id,
                sender_agent_id=source.producer_agent_id,
                recipient_agent_id=instance.agent_id,
                task_id=source.task_id,
                message_type="peer_review_requested",
                artifact_ids=(source.artifact_id,),
                public_summary=(
                    "Published Candidate released from isolation for independent "
                    "Solver peer review"
                ),
            )
            return (
                "peer_review",
                "peer_review_candidate",
                "PeerReviewArtifact",
                "peer_review_published",
                recipient.role,
                recipient.agent_id,
                thread.thread_id,
                request.message_id,
                False,
            )
        if source.artifact_type == "PeerReviewArtifact":
            thread_id = self._review_thread_by_artifact.get(source.artifact_id, "")
            if not thread_id:
                raise ValueError("PeerReview Artifact has no open review thread")
            return (
                "rebuttal",
                "respond_to_peer_review",
                "RebuttalArtifact",
                "rebuttal_published",
                recipient.role,
                recipient.agent_id,
                thread_id,
                self.mailbox.latest_message_id(thread_id),
                True,
            )
        raise ValueError("collaboration Turn input Artifact is invalid")

    def _task_plan(
        self,
        role: str,
        descriptor: str,
    ) -> tuple[str, int, tuple[str, ...], str, str, str]:
        plan = self._effective_execution_plan
        if plan is None or role == "RouterPlanner":
            return "", 0, (), "", "", ""
        proposals = [
            branch
            for branch in plan.branches
            if branch.agent_role == role
        ]
        if not proposals:
            return plan.plan_id, plan.version, (), "", "", ""
        if descriptor.startswith("new-branch-"):
            used_methods = {
                context.method_family
                for context in self._turn_contexts.values()
                if context.role in {"PrimarySolver", "AlternativeSolver"}
                and context.method_family
            }
            proposal = next(
                (
                    item
                    for item in proposals
                    if item.method_family not in used_methods
                ),
                proposals[-1],
            )
            return (
                plan.plan_id,
                plan.version,
                proposal.subgoal_ids,
                proposal.method_family,
                proposal.shared_context_hash,
                proposal.branch_context_hash,
            )
        index = 0
        if role == "AlternativeSolver":
            match = re.search(r"(\d+)$", descriptor)
            if match:
                index = max(0, int(match.group(1)) - 1)
        proposal = proposals[min(index, len(proposals) - 1)]
        return (
            plan.plan_id,
            plan.version,
            proposal.subgoal_ids,
            proposal.method_family,
            proposal.shared_context_hash,
            proposal.branch_context_hash,
        )

    def mark_dispatched(self, turn_id: str, *, budget_snapshot: dict[str, Any] | None = None) -> None:
        with self._lock:
            context = self._turn_contexts[turn_id]
            self._reject_stale_solver_turn(context)
            state = next(item["state"] for item in self.agents.snapshot() if item["agent_id"] == context.agent_id)
            if state["status"] != "running":
                self.agents.transition(context.agent_id, "running")
            self.tasks.transition(context.task_id, "running")
            current = next(item["state"] for item in self.agents.snapshot() if item["agent_id"] == context.agent_id)
            self.agents.update(context.agent_id, model_call_count=current["model_call_count"] + 1, budget_snapshot=dict(budget_snapshot or {}))
            self._turns[turn_id] = replace(self._turns[turn_id], status="dispatched")
            self._record_protocol_event(
                "model_turn_dispatched",
                turn_id=turn_id,
                agent_id=context.agent_id,
                task_id=context.task_id,
            )

    def complete_model_turn(
        self,
        turn_id: str,
        response: str,
        *,
        agent_action_protocol: bool = False,
        response_truncated: bool = False,
        truncation_reason: str = "",
        recovery_metadata: dict[str, str] | None = None,
    ) -> dict[str, str]:
        with self._lock:
            self._ensure_active()
            context = self._turn_contexts[turn_id]
            self._reject_stale_solver_turn(context)
            recovery = dict(recovery_metadata or {})
            digest = recovery.get("response_sha256") or sha256(
                response.encode("utf-8")
            ).hexdigest()
            if agent_action_protocol:
                self._agent_action_turns = True
                try:
                    parsed = AgentTurnPayloadParser().parse(
                        response,
                        allowed_actions=self._actions.actions_for(context.role),
                        truncated=response_truncated,
                        truncation_reason=truncation_reason,
                    )
                except Exception:
                    self.agents.transition(
                        context.agent_id,
                        "ready",
                        failure_code="agent_turn_payload_invalid",
                    )
                    self.tasks.transition(context.task_id, "ready")
                    self._turns[turn_id] = replace(
                        self._turns[turn_id],
                        status="failed",
                        failure_code="agent_turn_payload_invalid",
                    )
                    raise
                payload = parsed.payload
                artifact_type, message_type, recipient_role = (
                    self._action_protocol_route(context, payload)
                )
            else:
                parsed = None
                payload = AgentTurnPayload(
                    protocol_version=PROTOCOL_SCHEMA_VERSION,
                    task_result_type=context.artifact_type,
                    action="publish_candidate" if context.artifact_type == "CandidateArtifact" else "complete",
                    public_state_delta={"turn_status": "completed"},
                    result_payload={"response_sha256": digest, "response_chars": len(response), "turn_kind": context.turn_kind},
                    outbound_intents=({"message_type": context.message_type, "recipient_role": context.recipient_role},),
                    progress_summary=f"{context.role} published {context.artifact_type}",
                    stop_reason="model_response_received",
                )
                artifact_type = context.artifact_type
                message_type = context.message_type
                recipient_role = context.recipient_role
            phase_permission = permission_for(context.role, context.task_type)
            if payload.action not in phase_permission.allowed_action_types:
                raise PermissionError("Agent phase cannot perform Action")
            if artifact_type not in phase_permission.writable_artifact_types:
                raise PermissionError(
                    f"{context.role} phase cannot write {artifact_type}"
                )
            if message_type not in phase_permission.outbound_message_types:
                raise PermissionError("Agent phase cannot send message type")
            previous = self.tasks.get(context.task_id).output_artifact_ids
            artifact_payload = payload.to_dict()
            if artifact_type == "CandidateArtifact":
                artifact_payload = self._public_candidate_artifact_payload(
                    artifact_payload
                )
            elif artifact_type in {"PeerReviewArtifact", "RebuttalArtifact"}:
                artifact_payload = self._public_collaboration_artifact_payload(
                    artifact_payload,
                    context,
                )
            artifact = self.artifacts.publish(
                artifact_type=artifact_type, producer_agent_id=context.agent_id, task_id=context.task_id,
                turn_id=context.turn_id,
                payload={
                    **artifact_payload,
                    "host_completion": {
                        "status": "partial" if response_truncated else "complete",
                        "truncation_reason": (
                            str(truncation_reason) if response_truncated else ""
                        ),
                        "response_sha256": digest,
                        "parse_tier": (
                            recovery.get("parse_tier")
                            or (
                                parsed.parse_tier
                                if parsed is not None
                                else "host_wrapped"
                            )
                        ),
                        "recovery_reason": (
                            recovery.get("recovery_reason")
                            or (parsed.recovery_reason if parsed is not None else "")
                        ),
                        "assurance_degradation": (
                            recovery.get("assurance_degradation")
                            or (
                                parsed.assurance_degradation
                                if parsed is not None
                                else "none"
                            )
                        ),
                    },
                },
                parent_artifact_ids=(
                    tuple(context.input_artifact_ids)
                    if context.input_artifact_ids
                    else (previous[-1],) if previous else ()
                ),
            )
            self.tasks.append_output(context.task_id, artifact.artifact_id)
            self.agents.append(context.agent_id, "output_artifact_ids", artifact.artifact_id)
            self._record_protocol_event(
                "artifact_published",
                artifact_id=artifact.artifact_id,
                artifact_type=artifact.artifact_type,
                producer_agent_id=artifact.producer_agent_id,
                task_id=artifact.task_id,
                turn_id=artifact.turn_id,
            )
            recipient = (
                self.agents.instance(context.recipient_agent_id)
                if context.recipient_agent_id
                else self._ensure_agent(
                    recipient_role,
                    self._mailbox_descriptor(recipient_role, context),
                )
            )
            thread_id = context.thread_id
            if not thread_id:
                pair = tuple(sorted((context.agent_id, recipient.agent_id)))
                thread_id = self._thread_keys.get(pair)
                if not thread_id:
                    thread_id = self.mailbox.create_thread((context.agent_id, recipient.agent_id)).thread_id
                    self._thread_keys[pair] = thread_id
            message = self.mailbox.send(
                thread_id=thread_id, sender_agent_id=context.agent_id, recipient_agent_id=recipient.agent_id,
                task_id=context.task_id, message_type=message_type, artifact_ids=(artifact.artifact_id,),
                public_summary=payload.progress_summary,
                reply_to_message_id=(
                    context.reply_to_message_id
                    or self.mailbox.latest_message_id(thread_id)
                ),
            )
            self._record_protocol_event(
                "message_sent",
                message_id=message.message_id,
                thread_id=message.thread_id,
                sender_agent_id=message.sender_agent_id,
                recipient_agent_id=message.recipient_agent_id,
                message_type=message.message_type,
                artifact_ids=list(message.artifact_ids),
            )
            if artifact_type == "PeerReviewArtifact":
                self._review_thread_by_artifact[artifact.artifact_id] = thread_id
            if context.close_thread_after_publish:
                self.mailbox.close(thread_id)
            if payload.action in {
                "publish_candidate",
                "challenge_candidate",
                "publish_rebuttal",
                "abstain",
            } and not response_truncated:
                self.tasks.transition(context.task_id, "completed")
            else:
                self.tasks.transition(context.task_id, "ready")
            self.agents.transition(context.agent_id, "ready")
            self._turns[turn_id] = replace(self._turns[turn_id], artifact_id=artifact.artifact_id, message_id=message.message_id, status="completed")
            self._record_protocol_event(
                "model_turn_completed",
                turn_id=turn_id,
                agent_id=context.agent_id,
                task_id=context.task_id,
                artifact_id=artifact.artifact_id,
                message_id=message.message_id,
                status="completed",
            )
            return {
                "agent_id": context.agent_id,
                "task_id": context.task_id,
                "turn_id": turn_id,
                "output_artifact_id": artifact.artifact_id,
                "message_id": message.message_id,
                "thread_id": thread_id,
            }

    def _reject_stale_solver_turn(self, context: TurnContext) -> None:
        if context.role not in {"PrimarySolver", "AlternativeSolver"}:
            return
        current = self._effective_execution_plan
        if (
            current is not None
            and context.plan_version
            and context.plan_version != current.version
        ):
            raise RuntimeError("stale Solver Turn cannot mutate protocol state")

    @staticmethod
    def _mailbox_descriptor(role: str, context: TurnContext) -> str:
        if role == "PrimarySolver":
            return "primary-1"
        if role == "AlternativeSolver":
            return "alternative-1"
        return "default"

    @staticmethod
    def _public_candidate_artifact_payload(
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Keep Candidate communication public without retaining full prose."""

        result = payload.get("result_payload", {})
        if not isinstance(result, dict):
            return payload
        public_result = {
            key: result[key]
            for key in (
                "method",
                "final_answer",
                "public_solution_steps",
                "claims",
                "assumptions",
                "theorems",
                "unresolved_obligations",
            )
            if key in result
        }
        return {**payload, "result_payload": public_result}

    @staticmethod
    def _public_collaboration_artifact_payload(
        payload: dict[str, Any],
        context: TurnContext,
    ) -> dict[str, Any]:
        result = payload.get("result_payload", {})
        if not isinstance(result, dict):
            return payload
        identity = (
            {"review_id": f"review-{context.turn_id}"}
            if context.artifact_type == "PeerReviewArtifact"
            else {"rebuttal_id": f"rebuttal-{context.turn_id}"}
        )
        return {
            **payload,
            "result_payload": {
                **identity,
                "producer_agent_id": context.agent_id,
                "recipient_agent_id": context.recipient_agent_id,
                "input_artifact_ids": list(context.input_artifact_ids),
                **result,
            },
        }

    def _action_protocol_route(
        self,
        context: TurnContext,
        payload: AgentTurnPayload,
    ) -> tuple[str, str, str]:
        handler = self._actions.resolve(context, payload)
        artifact_type = handler.artifact_type
        message_type = handler.message_type
        recipient_role = handler.recipient_role
        return artifact_type, message_type, recipient_role

    def fail_model_turn(self, turn_id: str, failure_code: str) -> None:
        with self._lock:
            context = self._turn_contexts.get(turn_id)
            if context is None or self._turns[turn_id].status in {"completed", "failed"}:
                return
            state = next(item["state"] for item in self.agents.snapshot() if item["agent_id"] == context.agent_id)
            if state["status"] == "running":
                self.agents.transition(context.agent_id, "ready", failure_code=failure_code)
                self.tasks.transition(context.task_id, "ready")
            self._turns[turn_id] = replace(self._turns[turn_id], status="failed", failure_code=str(failure_code))
            self._record_protocol_event(
                "model_turn_completed",
                turn_id=turn_id,
                agent_id=context.agent_id,
                task_id=context.task_id,
                status="failed",
                failure_code=str(failure_code),
            )

    def relay_turn_artifact(
        self,
        turn_id: str,
        *,
        recipient_role: str,
        message_type: str,
        public_summary: str,
    ) -> str:
        with self._lock:
            self._ensure_active()
            context = self._turn_contexts[turn_id]
            lineage = self._turns[turn_id]
            if not lineage.artifact_id:
                raise ValueError("completed Turn has no Artifact to relay")
            phase_permission = permission_for(context.role, context.task_type)
            if message_type not in phase_permission.outbound_message_types:
                raise PermissionError("Agent phase cannot relay message type")
            recipient = self._ensure_agent(
                recipient_role,
                self._mailbox_descriptor(recipient_role, context),
            )
            pair = tuple(sorted((context.agent_id, recipient.agent_id)))
            thread_id = self._thread_keys.get(pair)
            if not thread_id:
                thread_id = self.mailbox.create_thread(
                    (context.agent_id, recipient.agent_id)
                ).thread_id
                self._thread_keys[pair] = thread_id
            message = self.mailbox.send(
                thread_id=thread_id,
                sender_agent_id=context.agent_id,
                recipient_agent_id=recipient.agent_id,
                task_id=context.task_id,
                message_type=message_type,
                artifact_ids=(lineage.artifact_id,),
                public_summary=public_summary,
                reply_to_message_id=self.mailbox.latest_message_id(thread_id),
            )
            self._record_protocol_event(
                "message_sent",
                message_id=message.message_id,
                thread_id=message.thread_id,
                sender_agent_id=message.sender_agent_id,
                recipient_agent_id=message.recipient_agent_id,
                message_type=message.message_type,
                artifact_ids=list(message.artifact_ids),
            )
            return message.message_id

    def candidate_publication(self, candidate_id: str) -> dict[str, str]:
        """Return Host-owned publication lineage for a Solver Candidate."""

        with self._lock:
            agents = {
                row["agent_id"]: row
                for row in self.agents.snapshot()
                if row["descriptor"] == str(candidate_id)
                and row["role"] in {"PrimarySolver", "AlternativeSolver"}
            }
            artifacts = [
                item
                for item in self.artifacts.snapshot()
                if item["artifact_type"] == "CandidateArtifact"
                and item["producer_agent_id"] in agents
                and item["payload"].get("host_completion", {}).get("status")
                == "complete"
            ]
            if not artifacts:
                raise KeyError("Candidate publication lineage is unavailable")
            artifact = artifacts[-1]
            context = self._turn_contexts.get(artifact["turn_id"])
            return {
                "candidate_id": str(candidate_id),
                "author_agent_id": artifact["producer_agent_id"],
                "source_turn_id": artifact["turn_id"],
                "candidate_artifact_id": artifact["artifact_id"],
                "shared_context_hash": (
                    context.shared_context_hash if context is not None else ""
                ),
                "branch_context_hash": (
                    context.branch_context_hash if context is not None else ""
                ),
            }

    def publish_deterministic_decision(
        self,
        *,
        candidate_id: str,
        candidate_version: int,
        selection_mode: str,
        selection_reason: str,
        audit_artifact_id: str = "",
    ) -> dict[str, Any]:
        """Commit deterministic arbitration as a service-authored Artifact."""

        with self._lock:
            candidate = self.candidate_publication(candidate_id)
            parents = [candidate["candidate_artifact_id"]]
            if audit_artifact_id:
                parents.append(audit_artifact_id)
            artifact = self.artifacts.publish_deterministic_decision(
                payload={
                    "candidate_id": str(candidate_id),
                    "candidate_version": int(candidate_version),
                    "selection_mode": str(selection_mode),
                    "selection_reason": str(selection_reason),
                    "audit_artifact_id": str(audit_artifact_id),
                    "authority": "deterministic_host_arbitration",
                    "status": "committed",
                },
                parent_artifact_ids=tuple(dict.fromkeys(parents)),
            )
            self._record_protocol_event(
                "artifact_published",
                artifact_id=artifact.artifact_id,
                artifact_type=artifact.artifact_type,
                producer_agent_id="",
                producer_kind=artifact.producer_kind,
                task_id="",
                turn_id="",
            )
            return artifact.to_dict()

    def reopen_review_thread(
        self,
        thread_id: str,
        *,
        new_candidate_artifact_id: str,
    ) -> None:
        with self._lock:
            self.mailbox.reopen(
                thread_id,
                new_artifact_id=new_candidate_artifact_id,
            )

    def finalize(self, model_call_records: list[dict[str, Any]]) -> dict[str, Any]:
        with self._lock:
            mailbox_snapshot = self.mailbox.snapshot()
            for thread in mailbox_snapshot["threads"]:
                if thread["status"] == "open":
                    self.mailbox.close(thread["thread_id"])
            terminal_status = self._interrupted_terminal_status()
            tasks = self.tasks.snapshot()
            for task in tasks:
                if task["status"] in {"ready", "running"}:
                    self.tasks.transition(task["task_id"], terminal_status)
            tasks = self.tasks.snapshot()
            for row in self.agents.snapshot():
                if row["state"]["status"] not in TERMINAL_AGENT_STATES:
                    assigned = [
                        task
                        for task in tasks
                        if task["assigned_agent_id"] == row["agent_id"]
                    ]
                    target = (
                        "completed"
                        if assigned
                        and all(task["status"] == "completed" for task in assigned)
                        else terminal_status
                    )
                    self.agents.transition(
                        row["agent_id"],
                        target,
                        failure_code=("" if target == "completed" else target),
                    )
            for row in self.agents.snapshot():
                state = row["state"]
                self._record_protocol_event(
                    "agent_stopped",
                    agent_id=row["agent_id"],
                    role=row["role"],
                    mode=row["mode"],
                    status=state["status"],
                    model_call_count=state["model_call_count"],
                    failure_code=state["failure_code"],
                )
            artifacts = self.artifacts.snapshot()
            mailbox_snapshot = self.mailbox.snapshot()
            turns = [item.to_dict() for item in self._turns.values()]
            messages_by_id = {
                item["message_id"]: item
                for item in mailbox_snapshot["messages"]
            }
            consumed_ids = {
                item["message_id"]
                for item in mailbox_snapshot["message_consumptions"]
            }
            recipient_called_mismatches = []
            for receipt in mailbox_snapshot["message_consumptions"]:
                message = messages_by_id.get(receipt["message_id"])
                context = self._turn_contexts.get(receipt["turn_id"])
                if (
                    message is None
                    or context is None
                    or message["recipient_agent_id"]
                    != receipt["consumer_agent_id"]
                    or context.agent_id != receipt["consumer_agent_id"]
                    or not set(message["artifact_ids"])
                    <= set(context.input_artifact_ids)
                ):
                    recipient_called_mismatches.append(receipt["receipt_id"])
            return {
                "schema_version": PROTOCOL_SCHEMA_VERSION,
                "mode": (
                    "autonomous_agent_action"
                    if self._agent_action_turns
                    else (
                        "hybrid_router_authoritative"
                        if self._authoritative_plan is not None
                        else "shadow_protocol"
                    )
                ),
                "selection_authority": (
                    "authoritative_router_then_agent_actions"
                    if self._agent_action_turns
                    else (
                        "authoritative_router_plan_then_legacy_candidate_flow"
                        if self._authoritative_plan is not None
                        else "legacy_flow"
                    )
                ),
                "active_plan_id": (
                    self._authoritative_plan.plan_id
                    if self._authoritative_plan is not None
                    else ""
                ),
                "counts": {"model_calls": len(model_call_records), "turns": len(turns), "agents": len(self.agents.snapshot()), "tasks": len(self.tasks.snapshot()), "artifacts": len(artifacts), "messages": len(mailbox_snapshot["messages"]), "message_consumptions": len(mailbox_snapshot["message_consumptions"]), "threads": len(mailbox_snapshot["threads"])},
                "call_turn_count_match": len(model_call_records) == len(turns), "agents": self.agents.snapshot(), "tasks": self.tasks.snapshot(),
                "communication_integrity": {
                    "recipient_called_mismatch_count": len(
                        recipient_called_mismatches
                    ),
                    "mismatched_receipt_ids": recipient_called_mismatches,
                    "consumed_message_count": len(consumed_ids),
                    "unconsumed_message_ids": [
                        item["message_id"]
                        for item in mailbox_snapshot["messages"]
                        if item["message_id"] not in consumed_ids
                    ],
                },
                "artifacts": artifacts, "messages": mailbox_snapshot["messages"], "message_consumptions": mailbox_snapshot["message_consumptions"], "threads": mailbox_snapshot["threads"], "turn_lineage": turns,
                "protocol_sequence": [dict(item) for item in self._protocol_events],
            }

    def release(self) -> None:
        with self._lock:
            self.mailbox.clear()
            self.artifacts.clear()
            self.tasks.clear()
            self.agents.clear()
            self._agent_keys.clear()
            self._task_keys.clear()
            self._thread_keys.clear()
            self._turns.clear()
            self._turn_contexts.clear()
            self._review_thread_by_artifact.clear()
            self._plan_artifact_by_version.clear()
            self._protocol_events.clear()
            self._protocol_event_sequence = 0
            self._authoritative_plan = None
            self._agent_action_turns = False
            self._cancellation_token = None
            self._released = True

    @property
    def released(self) -> bool:
        return self._released

    def _ensure_active(self) -> None:
        if (
            self._cancellation_token is not None
            and self._cancellation_token.is_cancelled
        ):
            raise RuntimeError("Agent runtime cancellation requested")

    def _interrupted_terminal_status(self) -> str:
        reason = (
            self._cancellation_token.reason
            if self._cancellation_token is not None
            else ""
        ).casefold()
        if "deadline" in reason or "wall_clock" in reason:
            return "deadline_expired"
        if "abort" in reason:
            return "aborted"
        return "cancelled"
