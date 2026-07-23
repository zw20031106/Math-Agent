from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json


@dataclass(frozen=True)
class KnowledgeCard:
    id: str
    subject: str
    type: str
    title: str
    statement: str
    preconditions: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    common_failures: list[str] = field(default_factory=list)
    source_type: str = ""
    source_ref: str = ""
    trust_level: str = "reviewed"
    source_version: str = ""
    reviewer: str = ""
    review_date: str = ""
    content_hash: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "subject": self.subject,
            "type": self.type,
            "title": self.title,
            "statement": self.statement,
            "preconditions": list(self.preconditions),
            "exclusions": list(self.exclusions),
            "common_failures": list(self.common_failures),
            "source_type": self.source_type,
            "source_ref": self.source_ref,
            "trust_level": self.trust_level,
            "source_version": self.source_version,
            "reviewer": self.reviewer,
            "review_date": self.review_date,
            "content_hash": self.content_hash,
        }

    def computed_content_hash(self) -> str:
        content = {
            "id": self.id,
            "subject": self.subject,
            "type": self.type,
            "title": self.title,
            "statement": self.statement,
            "preconditions": list(self.preconditions),
            "exclusions": list(self.exclusions),
            "common_failures": list(self.common_failures),
            "source_type": self.source_type,
            "source_ref": self.source_ref,
            "source_version": self.source_version,
        }
        canonical = json.dumps(
            content,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, value: dict) -> "KnowledgeCard":
        return cls(
            id=str(value["id"]),
            subject=str(value["subject"]),
            type=str(value["type"]),
            title=str(value["title"]),
            statement=str(value["statement"]),
            preconditions=[str(item) for item in value.get("preconditions", [])],
            exclusions=[str(item) for item in value.get("exclusions", [])],
            common_failures=[str(item) for item in value.get("common_failures", [])],
            source_type=str(value["source_type"]),
            source_ref=str(value["source_ref"]),
            trust_level=str(value["trust_level"]),
            source_version=str(value.get("source_version", "")),
            reviewer=str(value.get("reviewer", "")),
            review_date=str(value.get("review_date", "")),
            content_hash=str(value.get("content_hash", "")),
        )


@dataclass(frozen=True)
class SearchHit:
    card: KnowledgeCard
    bm25_score: float
    trust_priority: int
    condition_score: int

    def to_dict(self) -> dict:
        return {
            "card": self.card.to_dict(),
            "bm25_score": self.bm25_score,
            "trust_priority": self.trust_priority,
            "condition_score": self.condition_score,
        }
