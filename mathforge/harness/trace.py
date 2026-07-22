from __future__ import annotations

import json
import re
from typing import Any

from mathforge.harness.events import JUDGE_EVENTS


_SENSITIVE_KEYS = re.compile(r"(secret|token|password|api[_-]?key|exception|traceback)", re.I)
_ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:\\|/(?:home|Users|root|tmp)/)[^\s]+")


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
        if len(self._events) >= self._max_events:
            if event == "fallback_used":
                self._events[-1] = item
            return
        proposed = [*self._events, item]
        if len(json.dumps(proposed, ensure_ascii=False, default=str)) <= self._max_chars:
            self._events.append(item)

    def build(self) -> list[dict[str, Any]]:
        return [dict(event) for event in self._events]

    @property
    def internal_events(self) -> list[dict[str, Any]]:
        return [dict(event) for event in self._internal_events]

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
