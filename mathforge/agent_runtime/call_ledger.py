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
