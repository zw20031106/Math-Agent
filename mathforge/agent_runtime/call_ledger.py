from __future__ import annotations

from copy import deepcopy


class CallLedger:
    """Append-only call identities with version-safe status updates."""

    def __init__(self) -> None:
        self._records: list[dict] = []

    @property
    def records(self) -> list[dict]:
        return self._records

    def start(self, payload: dict) -> int:
        index = len(self._records)
        record = {
            "call_id": f"call-{index + 1:04d}",
            "logical_call_index": index + 1,
            **deepcopy(payload),
        }
        self._records.append(record)
        return index

    def update(self, index: int, payload: dict) -> None:
        self._records[index].update(deepcopy(payload))

    def snapshot(self) -> list[dict]:
        return deepcopy(self._records)

    def accounting_snapshot(self) -> dict:
        """Aggregate physical records by the three required runtime identities."""

        by_role: dict[str, int] = {}
        by_action: dict[str, int] = {}
        by_task: dict[str, int] = {}
        by_status: dict[str, int] = {}
        dispatched = 0
        for record in self._records:
            role = str(record.get("agent_role", "")).strip() or "unassigned"
            action = str(record.get("action_category", "")).strip() or "unassigned"
            task = str(record.get("task_id", "")).strip() or "unassigned"
            status = str(record.get("status", "")).strip() or "unknown"
            by_role[role] = by_role.get(role, 0) + 1
            by_action[action] = by_action.get(action, 0) + 1
            by_task[task] = by_task.get(task, 0) + 1
            by_status[status] = by_status.get(status, 0) + 1
            dispatched += int(bool(record.get("dispatched")))
        return {
            "recorded_calls": len(self._records),
            "dispatched_calls": dispatched,
            "by_role": dict(sorted(by_role.items())),
            "by_action": dict(sorted(by_action.items())),
            "by_task": dict(sorted(by_task.items())),
            "by_status": dict(sorted(by_status.items())),
        }
