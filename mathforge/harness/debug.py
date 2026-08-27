from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
from threading import Lock
import traceback
from typing import Any, Protocol


_ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:\\|/(?:home|Users|root|tmp)/)[^\s\",]+")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(api[_-]?key|authorization|password|secret|token)\s*[:=]\s*[^\s,;]+"
)


class DebugSink(Protocol):
    def record(self, payload: dict[str, Any]) -> None: ...


class InMemoryDebugSink:
    """Thread-safe local sink intended for tests and opt-in diagnostics."""

    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []
        self._lock = Lock()

    @property
    def records(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(self._records)

    def record(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._records.append(deepcopy(payload))


class JsonlDebugSink:
    """Opt-in append-only local debug sink; never used by the judge path by default."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = Lock()

    def record(self, payload: dict[str, Any]) -> None:
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self._lock:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(serialized + "\n")


def sanitized_failure_record(
    error: Exception,
    *,
    session_id: str,
    phase: str,
    error_code: str,
    error_class: str = "",
    internal_events: list[dict[str, Any]],
) -> dict[str, Any]:
    stack = "".join(traceback.format_list(traceback.extract_tb(error.__traceback__)))
    return {
        "session_id": session_id,
        "phase": phase,
        "error_code": error_code,
        "error_class": str(error_class),
        "exception_type": type(error).__name__,
        "stack": _sanitize_text(stack)[:12000],
        "internal_events": _sanitize_value(internal_events[-128:]),
    }


def _sanitize_text(value: str) -> str:
    value = _ABSOLUTE_PATH.sub("[local-path]", value)
    return _SECRET_ASSIGNMENT.sub(r"\1=[redacted]", value)


def _sanitize_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _sanitize_text(value)[:2000]
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value[:128]]
    if isinstance(value, dict):
        return {
            str(key): _sanitize_value(item)
            for key, item in list(value.items())[:64]
            if not re.search(
                r"(?i)(?:api[_-]?key|authorization|password|secret|token|raw_context)",
                str(key),
            )
        }
    return _sanitize_text(str(value))[:500]
