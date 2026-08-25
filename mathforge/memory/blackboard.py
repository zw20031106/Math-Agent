from __future__ import annotations

import json
import re
from typing import Any

from mathforge.harness.fingerprints import semantic_fingerprint
from mathforge.memory.policies import READ_PERMISSIONS, WRITE_PERMISSIONS
from mathforge.memory.session_memory import MemoryItem, SessionMemory


class MemoryBlackboard:
    def __init__(self, memory: SessionMemory) -> None:
        self._memory = memory

    def publish(self, role: str, category: str, payload: dict[str, Any]) -> MemoryItem:
        if category not in WRITE_PERMISSIONS.get(role, frozenset()):
            raise PermissionError(f"{role} cannot write {category}")
        return self._memory.add(category, payload, role)

    def publish_host_summary(
        self,
        summary_type: str,
        payload: dict[str, Any],
    ) -> MemoryItem:
        """Publish a bounded, public Host summary for downstream role views."""
        if not isinstance(summary_type, str) or not summary_type.strip():
            raise ValueError("summary_type must be a non-empty string")
        _validate_public_summary(payload)
        summary = {
            "summary_type": summary_type.strip()[:80],
            **dict(payload),
            "summary_hash": semantic_fingerprint(payload),
        }
        return self.publish("Host", "summary", summary)

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


_FORBIDDEN_SUMMARY_KEY = re.compile(
    r"(?:private|secret|password|api[_-]?key|token|authorization|"
    r"raw[_-]?(?:response|prompt|completion)|solution[_-]?text|"
    r"chain[_-]?of[_-]?thought|scratchpad|exception|traceback)",
    re.I,
)
_ABSOLUTE_PATH = re.compile(r"(?:^[A-Za-z]:[\\/]|^/(?:Users|home|root|tmp)/)")


def _validate_public_summary(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("Host summary payload must be an object")

    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                key_text = str(key)
                if _FORBIDDEN_SUMMARY_KEY.search(key_text):
                    raise ValueError(f"private field is not allowed in summary: {path}.{key_text}")
                visit(child, f"{path}.{key_text}")
        elif isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")
        elif isinstance(value, str):
            if _ABSOLUTE_PATH.search(value.strip()):
                raise ValueError("absolute paths are not allowed in Host summary")
        elif value is None or isinstance(value, (bool, int, float)):
            return
        else:
            raise ValueError(f"unsupported summary value at {path}")

    visit(payload, "summary")
    try:
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise ValueError("Host summary must be JSON serializable") from error
    if len(serialized) > 12000:
        raise ValueError("Host summary exceeds its public size budget")
