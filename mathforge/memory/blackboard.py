from __future__ import annotations

from typing import Any

from mathforge.memory.policies import READ_PERMISSIONS, WRITE_PERMISSIONS
from mathforge.memory.session_memory import MemoryItem, SessionMemory


class MemoryBlackboard:
    def __init__(self, memory: SessionMemory) -> None:
        self._memory = memory

    def publish(self, role: str, category: str, payload: dict[str, Any]) -> MemoryItem:
        if category not in WRITE_PERMISSIONS.get(role, frozenset()):
            raise PermissionError(f"{role} cannot write {category}")
        return self._memory.add(category, payload, role)

    def view(
        self,
        role: str,
        *,
        categories: set[str] | frozenset[str] | None = None,
    ) -> list[dict]:
        allowed = READ_PERMISSIONS.get(role, frozenset())
        if categories is not None:
            allowed = allowed.intersection(categories)
        return [item.to_dict() for item in self._memory.read(allowed)]
