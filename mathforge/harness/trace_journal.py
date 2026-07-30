from __future__ import annotations

import json
import os
from pathlib import Path
import re
from threading import Lock
from typing import Any, Callable


_SAFE_IDENTIFIER = re.compile(r"[^A-Za-z0-9._-]+")


class JsonlTraceJournal:
    """Thread-safe, incremental sink for sanitized debug events."""

    def __init__(self, path: Path, *, truncate: bool = True) -> None:
        self._path = path
        self._lock = Lock()
        self._journal_seq = 0
        path.parent.mkdir(parents=True, exist_ok=True)
        if truncate:
            path.write_text("", encoding="utf-8")

    @property
    def path(self) -> Path:
        return self._path

    def record(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._journal_seq += 1
            payload = {
                "journal_seq": self._journal_seq,
                "trace_event": event,
            }
            serialized = json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
            with self._path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(serialized + "\n")
                handle.flush()
                os.fsync(handle.fileno())


class TraceJournalFactory:
    """Create one isolated journal per case and run attempt."""

    def __init__(
        self,
        directory: Path,
        *,
        attempt_id: str | None = None,
    ) -> None:
        self._directory = directory
        self._attempt_id = attempt_id or self._allocate_attempt_id(directory)
        self._journals: dict[str, JsonlTraceJournal] = {}
        self._lock = Lock()

    @property
    def attempt_id(self) -> str:
        return self._attempt_id

    def __call__(
        self,
        session_id: str,
        metadata: dict[str, Any],
    ) -> Callable[[dict[str, Any]], None]:
        identifier = metadata.get("idx", metadata.get("case_id", session_id))
        safe_identifier = _SAFE_IDENTIFIER.sub("_", str(identifier)).strip("._")
        if not safe_identifier:
            safe_identifier = "case"
        with self._lock:
            journal = self._journals.get(safe_identifier)
            if journal is None:
                journal = JsonlTraceJournal(
                    self._directory
                    / self._attempt_id
                    / f"{safe_identifier}.trace.jsonl"
                )
                self._journals[safe_identifier] = journal
            return journal.record

    @staticmethod
    def _allocate_attempt_id(directory: Path) -> str:
        directory.mkdir(parents=True, exist_ok=True)
        existing = {
            path.name
            for path in directory.iterdir()
            if path.is_dir() and re.fullmatch(r"attempt-\d{4,}", path.name)
        }
        number = 1
        while f"attempt-{number:04d}" in existing:
            number += 1
        return f"attempt-{number:04d}"
