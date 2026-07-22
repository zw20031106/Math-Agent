from __future__ import annotations

from copy import deepcopy
import json
from uuid import uuid4

from mathforge.context.snapshots import ContextSnapshot
from mathforge.context.validator import CompressionValidator
from mathforge.context.views import candidate_view


class ContextCompressor:
    def __init__(self, validator: CompressionValidator | None = None) -> None:
        self._validator = validator or CompressionValidator()

    def compress(
        self,
        snapshot: ContextSnapshot,
        *,
        role: str,
        focus_claim_ids: list[str] | None = None,
        max_chars: int = 24000,
    ) -> ContextSnapshot:
        allowed_claims = self._dependency_closure(snapshot.claim_graph, focus_claim_ids or [])
        candidates = [
            candidate_view(candidate, role, allowed_claims if role == "RepairAgent" else None)
            for candidate in snapshot.candidates
        ]
        compressed = ContextSnapshot(
            snapshot_id=f"ctx-{uuid4().hex[:12]}",
            raw_context_ref=snapshot.raw_context_ref,
            original_problem=snapshot.original_problem,
            conditions=list(dict.fromkeys(snapshot.conditions)),
            final_answer=snapshot.final_answer,
            candidates=candidates,
            evidence=self._deduplicate(snapshot.evidence),
            obligations=self._deduplicate(snapshot.obligations),
            claim_graph={
                key: list(value)
                for key, value in snapshot.claim_graph.items()
                if role != "RepairAgent" or key in allowed_claims
            },
            metadata={"view_role": role, "compressed_from": snapshot.snapshot_id},
        )
        self._trim_soft_content(compressed, max_chars)
        return snapshot if self._validator.validate(snapshot, compressed) else compressed

    @staticmethod
    def _dependency_closure(graph: dict[str, list[str]], roots: list[str]) -> set[str]:
        closure: set[str] = set()
        stack = list(roots)
        while stack:
            claim_id = stack.pop()
            if claim_id in closure:
                continue
            closure.add(claim_id)
            stack.extend(graph.get(claim_id, []))
        return closure

    @staticmethod
    def _deduplicate(items: list[dict]) -> list[dict]:
        result: list[dict] = []
        seen: set[str] = set()
        for item in items:
            key = json.dumps(item, sort_keys=True, ensure_ascii=False, default=str)
            if key not in seen:
                seen.add(key)
                result.append(deepcopy(item))
        return result

    @staticmethod
    def _trim_soft_content(snapshot: ContextSnapshot, max_chars: int) -> None:
        if len(json.dumps(snapshot.to_dict(), ensure_ascii=False, default=str)) <= max_chars:
            return
        snapshot.evidence = [
            record for record in snapshot.evidence if record.get("strength") == "hard"
        ]
        for candidate in snapshot.candidates:
            candidate.pop("solution_text", None)
