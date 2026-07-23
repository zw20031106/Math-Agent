from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import json
from copy import deepcopy


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


@dataclass(frozen=True)
class RoleContextView:
    role: str
    snapshot_id: str
    payload: dict[str, Any]
    max_chars: int

    @property
    def char_count(self) -> int:
        return len(self.to_prompt_json())

    def to_json(self) -> str:
        return json.dumps(
            self.payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

    def to_prompt_json(self) -> str:
        payload = deepcopy(self.payload)
        payload.pop("original_problem", None)
        payload.pop("raw_context_ref", None)
        payload["context_snapshot_id"] = self.snapshot_id
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "snapshot_id": self.snapshot_id,
            "payload": dict(self.payload),
            "max_chars": self.max_chars,
            "char_count": self.char_count,
        }
