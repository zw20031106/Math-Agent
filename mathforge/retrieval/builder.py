from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from mathforge.retrieval.schemas import KnowledgeCard


_SCHEMA = """
CREATE TABLE cards (
    id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    statement TEXT NOT NULL,
    preconditions TEXT NOT NULL,
    exclusions TEXT NOT NULL,
    common_failures TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    trust_level TEXT NOT NULL
);
CREATE VIRTUAL TABLE cards_fts USING fts5(
    id UNINDEXED,
    title,
    statement,
    preconditions,
    common_failures,
    tokenize='unicode61'
);
"""


def build_database(database: Path, cards: list[KnowledgeCard]) -> None:
    database.parent.mkdir(parents=True, exist_ok=True)
    if database.exists():
        database.unlink()
    with sqlite3.connect(database) as connection:
        connection.executescript(_SCHEMA)
        for card in cards:
            row = card.to_dict()
            for name in ("preconditions", "exclusions", "common_failures"):
                row[name] = json.dumps(row[name], ensure_ascii=False)
            connection.execute(
                """INSERT INTO cards VALUES (
                    :id, :subject, :type, :title, :statement, :preconditions,
                    :exclusions, :common_failures, :source_type, :source_ref, :trust_level
                )""",
                row,
            )
            connection.execute(
                "INSERT INTO cards_fts VALUES (?, ?, ?, ?, ?)",
                (
                    card.id,
                    card.title,
                    card.statement,
                    " ".join(card.preconditions),
                    " ".join(card.common_failures),
                ),
            )


def load_cards(path: Path) -> list[KnowledgeCard]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("knowledge card source must be a list")
    return [KnowledgeCard.from_dict(item) for item in payload]
