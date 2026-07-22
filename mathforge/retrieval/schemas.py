from __future__ import annotations

from dataclasses import dataclass, field


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
        }

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
        )
