from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import re
from threading import RLock
from typing import Any

from mathforge.agent_runtime.artifact_store import SessionArtifactStore
from mathforge.agent_runtime.definitions import AgentRegistry
from mathforge.agent_runtime.mailbox import SessionMailbox
from mathforge.agent_runtime.protocol import AgentTurnPayload, AgentTurnPayloadParser, PROTOCOL_SCHEMA_VERSION, TurnContext, TurnLineage
from mathforge.agent_runtime.router_protocol import AuthoritativePlan
from mathforge.agent_runtime.state import AgentInstance, AgentStateRegistry, AgentTaskRegistry, TERMINAL_AGENT_STATES


_ROLE_BY_STAGE = {
    "router": "RouterPlanner", "primary": "PrimarySolver", "alternative": "AlternativeSolver",
    "lemma": "LemmaCurator", "verifier": "VerifierSkeptic", "repair": "RepairAgent", "finalizer": "LLMFinalizer",
}
_MODE_BY_ROLE = {
    "RouterPlanner": "plan", "PrimarySolver": "solve", "AlternativeSolver": "solve",
    "LemmaCurator": "curate", "VerifierSkeptic": "cross_exam", "RepairAgent": "repair", "LLMFinalizer": "finalize",
}
_TASK_BY_ROLE = {
    "RouterPlanner": "route_and_plan", "PrimarySolver": "solve_primary", "AlternativeSolver": "solve_alternative",
    "LemmaCurator": "curate_lemmas", "VerifierSkeptic": "cross_exam_candidates", "RepairAgent": "repair_claims", "LLMFinalizer": "copy_finalize",
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
        self._sequence = 0
        self._authoritative_plan: AuthoritativePlan | None = None
        self._agent_action_turns = False
        self._released = False
        self._lock = RLock()

    def bind_authoritative_plan(self, plan: AuthoritativePlan) -> None:
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
            self._authoritative_plan = plan

    def publish_router_decision(
        self,
        *,
        route_payload: dict[str, Any],
        plan: AuthoritativePlan,
    ) -> dict[str, str]:
        with self._lock:
            self.bind_authoritative_plan(plan)
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
                payload=plan.to_dict(),
                parent_artifact_ids=(route_artifact.artifact_id,),
            )
            for artifact in (route_artifact, plan_artifact):
                self.tasks.append_output(router_context.task_id, artifact.artifact_id)
                self.agents.append(
                    router_context.agent_id,
                    "output_artifact_ids",
                    artifact.artifact_id,
                )
            recipient = self._ensure_agent("PrimarySolver", "primary-1")
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
            return {
                "route_artifact_id": route_artifact.artifact_id,
                "plan_artifact_id": plan_artifact.artifact_id,
                "plan_message_id": message.message_id,
            }

    def _ensure_agent(self, role: str, descriptor: str = "default") -> AgentInstance:
        key = (role, descriptor)
        agent_id = self._agent_keys.get(key)
        if agent_id:
            return self.agents.instance(agent_id)
        mode = _MODE_BY_ROLE[role]
        ordinal = 1 + sum(1 for item in self._agent_keys if item[0] == role)
        agent_id = f"{self.session_id}:{role}:{mode}:{ordinal}"
        instance = AgentInstance(agent_id, self.session_id, role, mode, descriptor)
        self.agents.create(instance)
        self._agent_keys[key] = agent_id
        return instance

    def begin_model_turn(self, *, stage: str, turn_kind: str, agent_hint: str = "") -> TurnContext:
        with self._lock:
            if self._released:
                raise RuntimeError("Agent runtime has been released")
            hinted_role = str(agent_hint).split(":", 1)[0]
            role = hinted_role if hinted_role in self.definitions.roles() else _ROLE_BY_STAGE.get(stage, "PrimarySolver")
            descriptor = (
                str(agent_hint).split(":", 1)[1]
                if ":" in str(agent_hint)
                else "default"
                if hinted_role in self.definitions.roles()
                else str(turn_kind)
            )
            instance = self._ensure_agent(role, descriptor or "default")
            task_type = _TASK_BY_ROLE[role]
            plan_id, subgoal_ids, method_family = self._task_plan(role, descriptor)
            key = (instance.agent_id, task_type, plan_id)
            task_id = self._task_keys.get(key)
            if not task_id:
                task_id = self.tasks.create(
                    task_type,
                    instance.agent_id,
                    plan_id=plan_id,
                    subgoal_ids=subgoal_ids,
                    method_family=method_family,
                ).task_id
                self._task_keys[key] = task_id
            artifact_type, message_type, recipient_role = _OUTPUT_BY_ROLE[role]
            if turn_kind == "solver_progress":
                artifact_type, message_type, recipient_role = "ProgressArtifact", "progress_shared", "RouterPlanner"
            self._sequence += 1
            turn_id = f"turn-{self.session_id[:8]}-{self._sequence:04d}"
            context = TurnContext(
                instance.agent_id,
                role,
                instance.mode,
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
            )
            self._turn_contexts[turn_id] = context
            self._turns[turn_id] = TurnLineage(instance.agent_id, task_id, turn_id)
            return context

    def _task_plan(
        self,
        role: str,
        descriptor: str,
    ) -> tuple[str, tuple[str, ...], str]:
        plan = self._authoritative_plan
        if plan is None or role == "RouterPlanner":
            return "", (), ""
        proposals = [
            proposal
            for proposal in plan.task_proposals
            if proposal.agent_role == role
        ]
        if not proposals:
            return plan.plan_id, (), ""
        index = 0
        if role == "AlternativeSolver":
            match = re.search(r"(\d+)$", descriptor)
            if match:
                index = max(0, int(match.group(1)) - 1)
        proposal = proposals[min(index, len(proposals) - 1)]
        return plan.plan_id, proposal.subgoal_ids, proposal.method_family

    def mark_dispatched(self, turn_id: str, *, budget_snapshot: dict[str, Any] | None = None) -> None:
        with self._lock:
            context = self._turn_contexts[turn_id]
            state = next(item["state"] for item in self.agents.snapshot() if item["agent_id"] == context.agent_id)
            if state["status"] != "running":
                self.agents.transition(context.agent_id, "running")
            self.tasks.transition(context.task_id, "running")
            current = next(item["state"] for item in self.agents.snapshot() if item["agent_id"] == context.agent_id)
            self.agents.update(context.agent_id, model_call_count=current["model_call_count"] + 1, budget_snapshot=dict(budget_snapshot or {}))
            self._turns[turn_id] = replace(self._turns[turn_id], status="dispatched")

    def complete_model_turn(
        self,
        turn_id: str,
        response: str,
        *,
        agent_action_protocol: bool = False,
        response_truncated: bool = False,
        truncation_reason: str = "",
    ) -> dict[str, str]:
        with self._lock:
            context = self._turn_contexts[turn_id]
            digest = sha256(response.encode("utf-8")).hexdigest()
            if agent_action_protocol:
                self._agent_action_turns = True
                try:
                    parsed = AgentTurnPayloadParser().parse(
                        response,
                        allowed_actions=self.definitions.get(
                            context.role
                        ).allowed_action_types,
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
            previous = self.tasks.get(context.task_id).output_artifact_ids
            artifact_payload = payload.to_dict()
            if artifact_type == "CandidateArtifact":
                artifact_payload = self._public_candidate_artifact_payload(
                    artifact_payload
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
                    },
                },
                parent_artifact_ids=(previous[-1],) if previous else (),
            )
            self.tasks.append_output(context.task_id, artifact.artifact_id)
            self.agents.append(context.agent_id, "output_artifact_ids", artifact.artifact_id)
            recipient = self._ensure_agent(
                recipient_role,
                self._mailbox_descriptor(recipient_role, context),
            )
            pair = tuple(sorted((context.agent_id, recipient.agent_id)))
            thread_id = self._thread_keys.get(pair)
            if not thread_id:
                thread_id = self.mailbox.create_thread((context.agent_id, recipient.agent_id)).thread_id
                self._thread_keys[pair] = thread_id
            message = self.mailbox.send(
                thread_id=thread_id, sender_agent_id=context.agent_id, recipient_agent_id=recipient.agent_id,
                task_id=context.task_id, message_type=message_type, artifact_ids=(artifact.artifact_id,),
                public_summary=payload.progress_summary, reply_to_message_id=self.mailbox.latest_message_id(thread_id),
            )
            if payload.action in {"publish_candidate", "abstain"} and not response_truncated:
                self.tasks.transition(context.task_id, "completed")
            else:
                self.tasks.transition(context.task_id, "ready")
            self.agents.transition(context.agent_id, "ready")
            self._turns[turn_id] = replace(self._turns[turn_id], artifact_id=artifact.artifact_id, message_id=message.message_id, status="completed")
            return {"agent_id": context.agent_id, "task_id": context.task_id, "turn_id": turn_id, "output_artifact_id": artifact.artifact_id, "message_id": message.message_id}

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
    def _action_protocol_route(
        context: TurnContext,
        payload: AgentTurnPayload,
    ) -> tuple[str, str, str]:
        expected = {
            "continue_reasoning": ("ProgressArtifact", "progress_shared", "RouterPlanner"),
            "request_lemma": ("ProgressArtifact", "lemma_requested", "LemmaCurator"),
            "request_tool_check": ("ToolRequestArtifact", "tool_check_requested", "RouterPlanner"),
            "request_replan": ("ProgressArtifact", "replan_requested", "RouterPlanner"),
            "publish_candidate": ("CandidateArtifact", "candidate_published", "VerifierSkeptic"),
            "abstain": ("CheckpointArtifact", "task_abstained", "RouterPlanner"),
            "complete": (context.artifact_type, context.message_type, context.recipient_role),
        }.get(payload.action)
        if expected is None:
            raise ValueError("Agent Action is not implemented by the F4 Host")
        artifact_type, message_type, recipient_role = expected
        if payload.task_result_type != artifact_type:
            raise ValueError("Agent Action task_result_type is inconsistent")
        if payload.outbound_intents:
            proposed = str(payload.outbound_intents[0].get("recipient_role", ""))
            if proposed in {
                "RouterPlanner",
                "PrimarySolver",
                "AlternativeSolver",
                "LemmaCurator",
                "VerifierSkeptic",
            }:
                recipient_role = proposed
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

    def relay_turn_artifact(
        self,
        turn_id: str,
        *,
        recipient_role: str,
        message_type: str,
        public_summary: str,
    ) -> str:
        with self._lock:
            context = self._turn_contexts[turn_id]
            lineage = self._turns[turn_id]
            if not lineage.artifact_id:
                raise ValueError("completed Turn has no Artifact to relay")
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
            return message.message_id

    def finalize(self, model_call_records: list[dict[str, Any]]) -> dict[str, Any]:
        with self._lock:
            mailbox_snapshot = self.mailbox.snapshot()
            for thread in mailbox_snapshot["threads"]:
                if thread["status"] == "open":
                    self.mailbox.close(thread["thread_id"])
            for task in self.tasks.snapshot():
                if task["status"] in {"ready", "running"}:
                    self.tasks.transition(task["task_id"], "completed")
            for row in self.agents.snapshot():
                if row["state"]["status"] not in TERMINAL_AGENT_STATES:
                    if row["state"]["status"] == "running":
                        self.agents.transition(row["agent_id"], "ready")
                    self.agents.transition(row["agent_id"], "completed")
            artifacts = self.artifacts.snapshot()
            mailbox_snapshot = self.mailbox.snapshot()
            turns = [item.to_dict() for item in self._turns.values()]
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
                "counts": {"model_calls": len(model_call_records), "turns": len(turns), "agents": len(self.agents.snapshot()), "tasks": len(self.tasks.snapshot()), "artifacts": len(artifacts), "messages": len(mailbox_snapshot["messages"]), "threads": len(mailbox_snapshot["threads"])},
                "call_turn_count_match": len(model_call_records) == len(turns), "agents": self.agents.snapshot(), "tasks": self.tasks.snapshot(),
                "artifacts": artifacts, "messages": mailbox_snapshot["messages"], "threads": mailbox_snapshot["threads"], "turn_lineage": turns,
            }

    def release(self) -> None:
        with self._lock:
            self.mailbox.clear()
            self.artifacts.clear()
            self.tasks.clear()
            self.agents.clear()
            self._agent_keys.clear(); self._task_keys.clear(); self._thread_keys.clear(); self._turns.clear(); self._turn_contexts.clear()
            self._authoritative_plan = None
            self._agent_action_turns = False
            self._released = True

    @property
    def released(self) -> bool:
        return self._released
