from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class SkillAblationReport:
    evidence_scope: str
    selection_precision: float
    selection_recall: float
    skill_on_accuracy: float
    skill_off_accuracy: float
    accuracy_delta: float
    tokens_added: int


def evaluate_contract_canary(records: Iterable[dict]) -> SkillAblationReport:
    """Score labeled contract canaries; this is not a model-quality benchmark."""

    rows = list(records)
    selected = sum(len(row.get("selected", ())) for row in rows)
    relevant = sum(len(row.get("expected", ())) for row in rows)
    true_positive = sum(len(set(row.get("selected", ())) & set(row.get("expected", ()))) for row in rows)
    on = sum(bool(row.get("skill_on_correct")) for row in rows)
    off = sum(bool(row.get("skill_off_correct")) for row in rows)
    count = len(rows)
    on_accuracy = on / count if count else 0.0
    off_accuracy = off / count if count else 0.0
    return SkillAblationReport(
        evidence_scope="synthetic_contract_canary",
        selection_precision=true_positive / selected if selected else 0.0,
        selection_recall=true_positive / relevant if relevant else 0.0,
        skill_on_accuracy=on_accuracy,
        skill_off_accuracy=off_accuracy,
        accuracy_delta=on_accuracy - off_accuracy,
        tokens_added=sum(int(row.get("tokens_added", 0)) for row in rows),
    )
