from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContextSnapshot:
    snapshot_id: str
    raw_context_ref: str
    original_problem: str
    conditions: list[str]
    final_answer: str
    candidates: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    obligations: list[dict[str, Any]] = field(default_factory=list)
    claim_graph: dict[str, list[str]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "raw_context_ref": self.raw_context_ref,
            "original_problem": self.original_problem,
            "conditions": list(self.conditions),
            "final_answer": self.final_answer,
            "candidates": [dict(item) for item in self.candidates],
            "evidence": [dict(item) for item in self.evidence],
            "obligations": [dict(item) for item in self.obligations],
            "claim_graph": {key: list(value) for key, value in self.claim_graph.items()},
            "metadata": dict(self.metadata),
        }
