from __future__ import annotations

import json
from contextlib import closing
from datetime import date
import os
from pathlib import Path
import sqlite3
import tempfile

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
    trust_level TEXT NOT NULL,
    source_version TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    review_date TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    verification_reviewers TEXT NOT NULL
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
    for card in cards:
        _validate_card(card)
    database.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{database.name}.",
        suffix=".tmp",
        dir=database.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    temporary.unlink()
    try:
        _write_database(temporary, cards)
        _validate_database(temporary, expected_count=len(cards))
        os.replace(temporary, database)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_database(database: Path, cards: list[KnowledgeCard]) -> None:
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            connection.executescript(_SCHEMA)
            for card in cards:
                row = card.to_dict()
                for name in (
                    "preconditions",
                    "exclusions",
                    "common_failures",
                    "verification_reviewers",
                ):
                    row[name] = json.dumps(row[name], ensure_ascii=False)
                connection.execute(
                    """INSERT INTO cards VALUES (
                        :id, :subject, :type, :title, :statement, :preconditions,
                        :exclusions, :common_failures, :source_type, :source_ref,
                        :trust_level, :source_version, :reviewer, :review_date,
                        :content_hash, :verification_reviewers
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


def _validate_database(database: Path, *, expected_count: int) -> None:
    uri = f"{database.resolve().as_uri()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity != ("ok",):
            raise sqlite3.DatabaseError("knowledge database integrity check failed")
        card_count = connection.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        fts_count = connection.execute("SELECT COUNT(*) FROM cards_fts").fetchone()[0]
        if card_count != expected_count or fts_count != expected_count:
            raise sqlite3.DatabaseError("knowledge database row count mismatch")


def load_cards(path: Path) -> list[KnowledgeCard]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("knowledge card source must be a list")
    cards = [KnowledgeCard.from_dict(item) for item in payload]
    for card in cards:
        _validate_card(card)
    return cards


def _validate_card(card: KnowledgeCard) -> None:
    if card.trust_level not in {"verified", "reviewed", "conflicted", "draft"}:
        raise ValueError(f"invalid trust level for {card.id}")
    if not card.source_version.strip():
        raise ValueError(f"missing source version for {card.id}")
    if not card.reviewer.strip():
        raise ValueError(f"missing reviewer for {card.id}")
    verification_reviewers = {
        reviewer.strip()
        for reviewer in card.verification_reviewers
        if reviewer.strip()
    }
    if card.trust_level == "verified" and len(verification_reviewers) < 2:
        raise ValueError(
            f"verified card requires two distinct reviewers for {card.id}"
        )
    try:
        date.fromisoformat(card.review_date)
    except ValueError as error:
        raise ValueError(f"invalid review date for {card.id}") from error
    if card.content_hash != card.computed_content_hash():
        raise ValueError(f"content hash mismatch for {card.id}")
