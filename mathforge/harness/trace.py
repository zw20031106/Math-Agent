from __future__ import annotations

import json
import re
from typing import Any

from mathforge.harness.events import JUDGE_EVENTS


_SENSITIVE_KEYS = re.compile(
    r"^(?:"
    r"secret|.*[_-]secret|password|passwd|.*[_-]password|api[_-]?key|"
    r".*[_-]api[_-]?key|(?:access|auth|bearer|refresh|private|session|id)[_-]?token|"
    r"authorization|credentials?|exception|traceback"
    r")$",
    re.I,
)
_ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:\\|/(?:home|Users|root|tmp)/)[^\s]+")
_TERMINAL_EVENTS = frozenset({"session_started", "budget_summary", "fallback_used"})


class TraceBuilder:
    def __init__(
        self,
        events: list[dict[str, Any]],
        *,
        max_chars: int = 12000,
        max_events: int = 64,
    ) -> None:
        self._events = events
        self._internal_events: list[dict[str, Any]] = []
        self._max_chars = max_chars
        self._max_events = max_events

    def add(self, event: str, **details: Any) -> None:
        self._internal_events.append({"event": event, **details})
        if event not in JUDGE_EVENTS:
            return
        sanitized = {
            key: self._sanitize(value)
            for key, value in details.items()
            if not _SENSITIVE_KEYS.search(key)
        }
        item = {"event": event, **sanitized}
        self._append_bounded(item)

    def build(self) -> list[dict[str, Any]]:
        return [dict(event) for event in self._events]

    @property
    def internal_events(self) -> list[dict[str, Any]]:
        return [dict(event) for event in self._internal_events]

    def _append_bounded(self, item: dict[str, Any]) -> None:
        event = str(item.get("event", ""))
        if event in _TERMINAL_EVENTS:
            self._events[:] = [
                existing
                for existing in self._events
                if existing.get("event") != event
            ]
            while len(self._events) >= self._max_events:
                if not self._evict_nonterminal():
                    self._events.pop(0)
            self._events.append(item)
            while self._serialized_size() > self._max_chars:
                if not self._evict_nonterminal():
                    self._events.pop(0)
                    if not self._events:
                        break
            return
        if len(self._events) >= self._max_events:
            return
        self._events.append(item)
        if self._serialized_size() > self._max_chars:
            self._events.pop()

    def _evict_nonterminal(self) -> bool:
        for index in range(len(self._events) - 1, -1, -1):
            if self._events[index].get("event") not in _TERMINAL_EVENTS:
                self._events.pop(index)
                return True
        return False

    def _serialized_size(self) -> int:
        return len(json.dumps(self._events, ensure_ascii=False, default=str))

    @classmethod
    def _sanitize(cls, value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return _ABSOLUTE_PATH.sub("[local-path]", value)[:1000]
        if isinstance(value, (list, tuple)):
            return [cls._sanitize(item) for item in value[:32]]
        if isinstance(value, dict):
            return {
                str(key): cls._sanitize(item)
                for key, item in list(value.items())[:32]
                if not _SENSITIVE_KEYS.search(str(key))
            }
        return str(value)[:200]
