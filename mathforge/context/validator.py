from __future__ import annotations

from mathforge.context.invariants import hard_evidence_ids, required_obligation_ids
from mathforge.context.snapshots import ContextSnapshot


class CompressionValidator:
    def validate(self, original: ContextSnapshot, compressed: ContextSnapshot) -> list[str]:
        errors: list[str] = []
        if compressed.original_problem != original.original_problem:
            errors.append("original_problem_changed")
        if not set(original.conditions) <= set(compressed.conditions):
            errors.append("conditions_removed")
        if original.final_answer and compressed.final_answer != original.final_answer:
            errors.append("final_answer_changed")
        if not hard_evidence_ids(original) <= hard_evidence_ids(compressed):
            errors.append("hard_evidence_removed")
        if not required_obligation_ids(original) <= required_obligation_ids(compressed):
            errors.append("required_obligation_removed")
        return errors
