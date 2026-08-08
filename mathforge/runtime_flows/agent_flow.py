from __future__ import annotations

from typing import Any, Iterable


class AgentEventProjector:
    """Project protocol state into public, bounded lifecycle events.

    The projection carries identifiers, statuses and public summaries only;
    Artifact payloads and model response text remain in the protocol snapshot.
    """

    def project(
        self,
        snapshot: dict[str, Any],
        *,
        repair_lineage: Iterable[dict[str, Any]] = (),
    ) -> list[tuple[str, dict[str, Any]]]:
        events: list[tuple[str, dict[str, Any]]] = []
        agents = list(snapshot.get("agents", ()))
        tasks = sorted(
            snapshot.get("tasks", ()),
            key=lambda item: int(item.get("created_sequence", 0)),
        )
        turns = list(snapshot.get("turn_lineage", ()))
        artifacts = list(snapshot.get("artifacts", ()))
        messages = sorted(
            snapshot.get("messages", ()),
            key=lambda item: int(item.get("sequence", 0)),
        )

        for item in agents:
            events.append(
                (
                    "agent_created",
                    {
                        "agent_id": item.get("agent_id", ""),
                        "role": item.get("role", ""),
                        "mode": item.get("mode", ""),
                        "descriptor": item.get("descriptor", ""),
                    },
                )
            )
        for item in tasks:
            events.append(
                (
                    "task_assigned",
                    {
                        "task_id": item.get("task_id", ""),
                        "task_type": item.get("task_type", ""),
                        "assigned_agent_id": item.get("assigned_agent_id", ""),
                        "plan_id": item.get("plan_id", ""),
                        "subgoal_ids": list(item.get("subgoal_ids", ())),
                        "method_family": item.get("method_family", ""),
                    },
                )
            )
        for item in turns:
            common = {
                "turn_id": item.get("turn_id", ""),
                "agent_id": item.get("agent_id", ""),
                "task_id": item.get("task_id", ""),
            }
            events.append(("model_turn_started", dict(common)))
            events.append(
                (
                    "model_turn_completed",
                    {
                        **common,
                        "status": item.get("status", ""),
                        "failure_code": item.get("failure_code", ""),
                        "artifact_id": item.get("artifact_id", ""),
                    },
                )
            )
        for item in artifacts:
            events.append(
                (
                    "artifact_published",
                    {
                        "artifact_id": item.get("artifact_id", ""),
                        "artifact_type": item.get("artifact_type", ""),
                        "producer_agent_id": item.get("producer_agent_id", ""),
                        "producer_kind": item.get("producer_kind", "agent"),
                        "task_id": item.get("task_id", ""),
                        "turn_id": item.get("turn_id", ""),
                        "parent_artifact_ids": list(
                            item.get("parent_artifact_ids", ())
                        ),
                    },
                )
            )
        for item in messages:
            public = {
                "message_id": item.get("message_id", ""),
                "thread_id": item.get("thread_id", ""),
                "sender_agent_id": item.get("sender_agent_id", ""),
                "recipient_agent_id": item.get("recipient_agent_id", ""),
                "message_type": item.get("message_type", ""),
                "artifact_ids": list(item.get("artifact_ids", ())),
                "reply_to_message_id": item.get("reply_to_message_id", ""),
                "public_summary": item.get("public_summary", ""),
            }
            events.append(("message_sent", dict(public)))
            events.append(
                (
                    "message_delivered",
                    {**public, "delivery_status": "accepted_by_session_mailbox"},
                )
            )
        for item in repair_lineage:
            if bool(item.get("rolled_back")):
                events.append(
                    (
                        "repair_rolled_back",
                        self._repair_event(item),
                    )
                )
            elif item.get("proposed_candidate_id"):
                events.append(
                    (
                        "repair_committed",
                        self._repair_event(item),
                    )
                )
        for item in agents:
            state = dict(item.get("state", {}))
            events.append(
                (
                    "agent_stopped",
                    {
                        "agent_id": item.get("agent_id", ""),
                        "role": item.get("role", ""),
                        "mode": item.get("mode", ""),
                        "status": state.get("status", ""),
                        "model_call_count": state.get("model_call_count", 0),
                        "failure_code": state.get("failure_code", ""),
                    },
                )
            )
        return events

    @staticmethod
    def _repair_event(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "source_candidate_id": item.get("source_candidate_id", ""),
            "proposed_candidate_id": item.get("proposed_candidate_id", ""),
            "repair_artifact_id": item.get("repair_artifact_id", ""),
            "affected_claim_ids": list(item.get("affected_claim_ids", ())),
            "reverified": bool(item.get("reverified")),
            "reason": item.get("reason", ""),
        }
