from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class MemoryItem:
    item_id: str
    category: str
    payload: dict[str, Any]
    writer: str

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "category": self.category,
            "payload": dict(self.payload),
            "writer": self.writer,
        }


class SessionMemory:
    """Per-problem storage; it is never shared between solve calls."""

    def __init__(self) -> None:
        self._items: list[MemoryItem] = []
        self._lock = Lock()

    def add(self, category: str, payload: dict[str, Any], writer: str) -> MemoryItem:
        item = MemoryItem(f"mem-{uuid4().hex[:12]}", category, dict(payload), writer)
        with self._lock:
            self._items.append(item)
        return item

    def read(self, categories: set[str] | frozenset[str]) -> list[MemoryItem]:
        with self._lock:
            return [item for item in self._items if item.category in categories]

    def to_dict(self) -> dict:
        with self._lock:
            return {"items": [item.to_dict() for item in self._items]}

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
