from __future__ import annotations

from typing import Any


class TraceBuilder:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events

    def add(self, event: str, **details: Any) -> None:
        self._events.append({"event": event, **details})

    def build(self) -> list[dict[str, Any]]:
        return [dict(event) for event in self._events]
