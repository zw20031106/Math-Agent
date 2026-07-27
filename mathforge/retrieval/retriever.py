from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3

from mathforge.harness.fingerprints import file_fingerprint
from mathforge.resources import resource_path
from mathforge.retrieval.schemas import (
    RAG_SCHEMA_VERSION,
    KnowledgeCard,
    RetrievalStatus,
    SearchHit,
    SearchResult,
)


_TRUST_PRIORITY = {
    "verified": 0,
    "reviewed": 1,
    "conflicted": 2,
}
_BILINGUAL_TERMS = {
    "方程": ("equation",),
    "不等式": ("inequality",),
    "平方": ("squaring",),
    "增根": ("extraneous", "root"),
    "三角形": ("triangle",),
    "圆": ("circle",),
    "几何": ("geometry",),
    "退化": ("degenerate",),
    "整数": ("integer",),
    "整除": ("divisibility",),
    "同余": ("modulo",),
    "互素": ("coprimality",),
    "计数": ("counting",),
    "排列": ("permutation",),
    "组合": ("combination",),
    "概率": ("probability",),
    "密度": ("density",),
    "分布": ("distribution",),
    "归一化": ("normalization",),
    "极限": ("limit",),
    "积分": ("integral",),
    "导数": ("derivative",),
    "级数": ("series",),
    "交换": ("interchange",),
    "矩阵": ("matrix",),
    "向量": ("vector",),
    "特征值": ("eigenvalue",),
    "维数": ("dimension",),
    "微分方程": ("differential", "equation"),
    "初值": ("initial", "condition"),
    "边界条件": ("boundary", "condition"),
    "代入": ("substitution",),
}


class Retriever:
    def __init__(self, database: Path | None = None, max_top_k: int = 5) -> None:
        self._database = database or resource_path("data", "math_knowledge.sqlite")
        self._max_top_k = max(1, max_top_k)

    @property
    def fingerprint(self) -> str:
        return file_fingerprint(self._database)

    def retrieve(
        self,
        query: str,
        *,
        subject: str | None = None,
        card_type: str | None = None,
        role: str = "PrimarySolver",
        top_k: int = 3,
    ) -> list[KnowledgeCard]:
        return [
            hit.card
            for hit in self.search(
                query,
                subject=subject,
                card_type=card_type,
                role=role,
                top_k=top_k,
            )
        ]

    def search(
        self,
        query: str,
        *,
        subject: str | None = None,
        card_type: str | None = None,
        role: str = "PrimarySolver",
        top_k: int = 3,
    ) -> list[SearchHit]:
        return self.search_with_status(
            query,
            subject=subject,
            card_type=card_type,
            role=role,
            top_k=top_k,
        ).hits

    def search_with_status(
        self,
        query: str,
        *,
        subject: str | None = None,
        card_type: str | None = None,
        role: str = "PrimarySolver",
        top_k: int = 3,
    ) -> SearchResult:
        if not self._database.exists():
            return SearchResult(
                RAG_SCHEMA_VERSION,
                RetrievalStatus.MISSING_DB,
                [],
            )
        match_query = self._match_query(query)
        if not match_query:
            return SearchResult(
                RAG_SCHEMA_VERSION,
                RetrievalStatus.NO_MATCH,
                [],
            )
        result_limit = min(max(1, top_k), self._max_top_k)
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
        sql += """
            ORDER BY
              CASE c.trust_level
                WHEN 'verified' THEN 0
                WHEN 'reviewed' THEN 1
                WHEN 'conflicted' THEN 2
                ELSE 3
              END ASC,
              rank ASC,
              c.id ASC
        """
        try:
            uri = f"{self._database.resolve().as_uri()}?mode=ro"
            with closing(sqlite3.connect(uri, uri=True)) as connection:
                rows = connection.execute(sql, parameters).fetchall()
        except sqlite3.OperationalError as error:
            message = str(error).lower()
            status = (
                RetrievalStatus.FTS_UNAVAILABLE
                if "fts" in message or "no such table" in message
                else RetrievalStatus.QUERY_ERROR
            )
            return SearchResult(RAG_SCHEMA_VERSION, status, [])
        except (sqlite3.Error, OSError):
            return SearchResult(
                RAG_SCHEMA_VERSION,
                RetrievalStatus.QUERY_ERROR,
                [],
            )
        hits = [self._row_to_hit(query, row) for row in rows]
        hits.sort(
            key=lambda hit: (
                hit.trust_priority,
                -hit.condition_score,
                hit.bm25_score,
                hit.card.id,
            )
        )
        deduplicated: list[SearchHit] = []
        statements: set[str] = set()
        for hit in hits:
            normalized = " ".join(hit.card.statement.lower().split())
            if normalized not in statements:
                statements.add(normalized)
                deduplicated.append(hit)
            if len(deduplicated) >= result_limit:
                break
        return SearchResult(
            RAG_SCHEMA_VERSION,
            (
                RetrievalStatus.MATCHED
                if deduplicated
                else RetrievalStatus.NO_MATCH
            ),
            deduplicated,
        )

    @staticmethod
    def _match_query(query: str) -> str:
        lowered = query.lower()
        tokens = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}", lowered)
        for chinese, translations in _BILINGUAL_TERMS.items():
            if chinese in lowered:
                tokens.extend(translations)
        deduplicated = list(dict.fromkeys(tokens))
        return " OR ".join(f'"{token}"' for token in deduplicated[:24])

    @staticmethod
    def _condition_overlap(query: str, card: KnowledgeCard) -> int:
        lowered = query.lower()
        return sum(condition.lower() in lowered for condition in card.preconditions)

    @staticmethod
    def _row_to_hit(query: str, row: tuple) -> SearchHit:
        card = KnowledgeCard(
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
            source_version=row[11],
            reviewer=row[12],
            review_date=row[13],
            content_hash=row[14],
            verification_reviewers=json.loads(row[15]),
        )
        return SearchHit(
            card=card,
            bm25_score=float(row[16]),
            trust_priority=_TRUST_PRIORITY[card.trust_level],
            condition_score=Retriever._condition_overlap(query, card),
        )
