from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3

from mathforge.retrieval.schemas import KnowledgeCard


class Retriever:
    def __init__(self, database: Path | None = None, max_top_k: int = 5) -> None:
        self._database = database or Path(__file__).resolve().parents[2] / "data" / "math_knowledge.sqlite"
        self._max_top_k = max(1, max_top_k)

    def retrieve(
        self,
        query: str,
        *,
        subject: str | None = None,
        card_type: str | None = None,
        role: str = "PrimarySolver",
        top_k: int = 3,
    ) -> list[KnowledgeCard]:
        if not self._database.exists():
            return []
        match_query = self._match_query(query)
        if not match_query:
            return []
        trust_levels = ("verified", "reviewed", "conflicted") if role == "VerifierSkeptic" else ("verified", "reviewed")
        placeholders = ",".join("?" for _ in trust_levels)
        sql = f"""
            SELECT c.*, bm25(cards_fts) AS rank
            FROM cards_fts
            JOIN cards c ON c.id = cards_fts.id
            WHERE cards_fts MATCH ?
              AND c.trust_level IN ({placeholders})
        """
        parameters: list[object] = [match_query, *trust_levels]
        if subject:
            sql += " AND c.subject IN (?, 'general-math')"
            parameters.append(subject)
        if card_type:
            sql += " AND c.type = ?"
            parameters.append(card_type)
        sql += " ORDER BY rank ASC, c.trust_level ASC, c.id ASC LIMIT ?"
        parameters.append(min(max(1, top_k * 3), self._max_top_k * 3))
        try:
            uri = f"{self._database.resolve().as_uri()}?mode=ro"
            with sqlite3.connect(uri, uri=True) as connection:
                rows = connection.execute(sql, parameters).fetchall()
        except (sqlite3.Error, OSError):
            return []
        cards = [self._row_to_card(row) for row in rows]
        cards.sort(key=lambda card: (-self._condition_overlap(query, card), card.id))
        deduplicated: list[KnowledgeCard] = []
        statements: set[str] = set()
        for card in cards:
            normalized = " ".join(card.statement.lower().split())
            if normalized not in statements:
                statements.add(normalized)
                deduplicated.append(card)
            if len(deduplicated) >= min(top_k, self._max_top_k):
                break
        return deduplicated

    @staticmethod
    def _match_query(query: str) -> str:
        tokens = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}", query.lower())
        return " OR ".join(f'"{token}"' for token in tokens[:24])

    @staticmethod
    def _condition_overlap(query: str, card: KnowledgeCard) -> int:
        lowered = query.lower()
        return sum(condition.lower() in lowered for condition in card.preconditions)

    @staticmethod
    def _row_to_card(row: tuple) -> KnowledgeCard:
        return KnowledgeCard(
            id=row[0],
            subject=row[1],
            type=row[2],
            title=row[3],
            statement=row[4],
            preconditions=json.loads(row[5]),
            exclusions=json.loads(row[6]),
            common_failures=json.loads(row[7]),
            source_type=row[8],
            source_ref=row[9],
            trust_level=row[10],
        )
