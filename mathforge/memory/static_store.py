from __future__ import annotations

from pathlib import Path
import sqlite3


class StaticKnowledgeStore:
    """Read-only access to trusted static knowledge."""

    def __init__(self, database: Path) -> None:
        self._database = database

    def query(self, sql: str, parameters: tuple = ()) -> list[tuple]:
        if not self._database.exists():
            return []
        uri = f"{self._database.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            return connection.execute(sql, parameters).fetchall()


class ExperienceStore(StaticKnowledgeStore):
    """Evaluation-time episodic/failure data is also opened read-only."""
