from __future__ import annotations

from copy import deepcopy
import json
from uuid import uuid4

from mathforge.context.errors import ContextBudgetExceeded
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
        if max_chars < 1:
            raise ContextBudgetExceeded("context budget must be positive")
        allowed_claims = self._dependency_closure(snapshot.claim_graph, focus_claim_ids or [])
        candidates = [
            candidate_view(candidate, role, allowed_claims if role == "RepairAgent" else None)
            for candidate in snapshot.candidates
        ]
        candidate_ids = {str(candidate.get("candidate_id")) for candidate in candidates}
        evidence = self._deduplicate(snapshot.evidence)
        if role == "RepairAgent":
            evidence = [
                record
                for record in evidence
                if (
                    not record.get("candidate_id")
                    or str(record.get("candidate_id")) in candidate_ids
                )
                and (
                    record.get("claim_id") is None
                    or str(record.get("claim_id")) in allowed_claims
                )
            ]
        compressed = ContextSnapshot(
            snapshot_id=f"ctx-{uuid4().hex[:12]}",
            raw_context_ref=snapshot.raw_context_ref,
            original_problem=snapshot.original_problem,
            conditions=list(dict.fromkeys(snapshot.conditions)),
            final_answer=snapshot.final_answer,
            candidates=candidates,
            evidence=evidence,
            obligations=self._deduplicate(snapshot.obligations),
            claim_graph={
                key: list(value)
                for key, value in snapshot.claim_graph.items()
                if role != "RepairAgent" or key in allowed_claims
            },
            metadata={
                **deepcopy(snapshot.metadata),
                "view_role": role,
                "compressed_from": snapshot.snapshot_id,
            },
        )
        self._trim_optional_content(compressed, role, max_chars)
        errors = self._validator.validate(snapshot, compressed)
        if errors:
            raise ContextBudgetExceeded(f"context invariant failure: {','.join(errors)}")
        size = self.serialized_size(compressed)
        if size > max_chars:
            raise ContextBudgetExceeded(
                f"required {role} context is {size} chars, budget is {max_chars}"
            )
        compressed.metadata["serialized_chars"] = size
        if self.serialized_size(compressed) > max_chars:
            compressed.metadata.pop("serialized_chars", None)
        return compressed

    @staticmethod
    def serialized_size(snapshot: ContextSnapshot) -> int:
        return len(json.dumps(snapshot.to_dict(), ensure_ascii=False, default=str))

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

    @classmethod
    def _trim_optional_content(
        cls,
        snapshot: ContextSnapshot,
        role: str,
        max_chars: int,
    ) -> None:
        if cls.serialized_size(snapshot) <= max_chars:
            return
        snapshot.evidence = [
            record for record in snapshot.evidence if record.get("strength") == "hard"
        ]
        snapshot.obligations = [
            obligation
            for obligation in snapshot.obligations
            if obligation.get("required", True)
        ]
        if cls.serialized_size(snapshot) <= max_chars:
            return
        memory = snapshot.metadata.get("authorized_memory")
        if isinstance(memory, list):
            snapshot.metadata["authorized_memory"] = [
                {
                    "item_id": item.get("item_id"),
                    "category": item.get("category"),
                    "writer": item.get("writer"),
                }
                for item in memory
                if isinstance(item, dict)
            ]
        if role not in {"RepairAgent", "VerifierSkeptic"}:
            snapshot.claim_graph = {}
        for candidate in snapshot.candidates:
            for key in (
                "parse_status",
                "version",
                "unresolved_obligations",
                "is_method_duplicate",
            ):
                candidate.pop(key, None)
