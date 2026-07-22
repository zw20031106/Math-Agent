from __future__ import annotations

from mathforge.context.snapshots import ContextSnapshot


def hard_evidence_ids(snapshot: ContextSnapshot) -> set[str]:
    return {
        str(record.get("evidence_id"))
        for record in snapshot.evidence
        if record.get("strength") == "hard"
    }


def required_obligation_ids(snapshot: ContextSnapshot) -> set[str]:
    return {
        str(item.get("obligation_id"))
        for item in snapshot.obligations
        if item.get("required", True)
    }
