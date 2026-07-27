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
    """Create one isolated journal per case without exposing its local path."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def __call__(
        self,
        session_id: str,
        metadata: dict[str, Any],
    ) -> Callable[[dict[str, Any]], None]:
        identifier = metadata.get("idx", metadata.get("case_id", session_id))
        safe_identifier = _SAFE_IDENTIFIER.sub("_", str(identifier)).strip("._")
        if not safe_identifier:
            safe_identifier = "case"
        journal = JsonlTraceJournal(
            self._directory / f"{safe_identifier}.trace.jsonl"
        )
        return journal.record
