from __future__ import annotations

from copy import deepcopy
import json
from uuid import uuid4

from mathforge.context.errors import ContextBudgetExceeded
from mathforge.context.snapshots import ContextSnapshot
from mathforge.context.validator import CompressionValidator
from mathforge.context.views import candidate_view
from mathforge.harness.context_budget import InternS2TokenCounter


class ContextCompressor:
    def __init__(
        self,
        validator: CompressionValidator | None = None,
        token_counter: InternS2TokenCounter | None = None,
    ) -> None:
        self._validator = validator or CompressionValidator()
        self._token_counter = token_counter or InternS2TokenCounter()

    def compress(
        self,
        snapshot: ContextSnapshot,
        *,
        role: str,
        focus_claim_ids: list[str] | None = None,
        max_chars: int = 24000,
        max_tokens: int | None = None,
        core_token_budget: int | None = None,
    ) -> ContextSnapshot:
        if max_chars < 1:
            raise ContextBudgetExceeded("context budget must be positive")
        allowed_graph_nodes = self._dependency_closure(
            snapshot.claim_graph,
            focus_claim_ids or [],
        )
        allowed_claims = {
            claim_id.rsplit("::", 1)[-1]
            for claim_id in allowed_graph_nodes
        }
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
                if role != "RepairAgent" or key in allowed_graph_nodes
            },
            metadata={
                **deepcopy(snapshot.metadata),
                "view_role": role,
                "compressed_from": snapshot.snapshot_id,
            },
        )
        self._trim_optional_content(compressed, role, max_chars)
        if max_tokens is not None:
            if type(max_tokens) is not int or max_tokens < 1:
                raise ContextBudgetExceeded("token context budget must be positive")
            if core_token_budget is not None and (
                type(core_token_budget) is not int
                or core_token_budget < 1
                or core_token_budget > max_tokens
            ):
                raise ContextBudgetExceeded(
                    "core token budget must be positive and no greater than token budget"
                )
            self._trim_token_content(compressed, role, max_tokens)
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
        token_count = self._token_counter.count_text(
            self._prompt_text(compressed)
        )
        core_count = self._token_counter.count_text(
            self._core_text(compressed)
        )
        if core_token_budget is not None and core_count.tokens > core_token_budget:
            raise ContextBudgetExceeded(
                f"required {role} core context is {core_count.tokens} tokens, "
                f"budget is {core_token_budget}"
            )
        if max_tokens is not None and token_count.tokens > max_tokens:
            raise ContextBudgetExceeded(
                f"required {role} context is {token_count.tokens} tokens, "
                f"budget is {max_tokens}"
            )
        compressed.metadata.update(
            {
                "token_count": token_count.tokens,
                "token_budget": max_tokens or 0,
                "core_token_count": core_count.tokens,
                "core_token_budget": core_token_budget or 0,
            }
        )
        # Metadata is part of the payload, so check the final serialized view.
        final_token_count = self._token_counter.count_text(
            self._prompt_text(compressed)
        )
        for _ in range(3):
            if compressed.metadata.get("token_count") == final_token_count.tokens:
                break
            compressed.metadata["token_count"] = final_token_count.tokens
            final_token_count = self._token_counter.count_text(
                self._prompt_text(compressed)
            )
        if max_tokens is not None and final_token_count.tokens > max_tokens:
            raise ContextBudgetExceeded(
                f"required {role} context metadata exceeds token budget"
            )
        final_size = self.serialized_size(compressed)
        if final_size > max_chars:
            self._trim_optional_content(compressed, role, max_chars)
            compressed.metadata["token_count"] = self._token_counter.count_text(
                self._prompt_text(compressed)
            ).tokens
            compressed.metadata["core_token_count"] = self._token_counter.count_text(
                self._core_text(compressed)
            ).tokens
            final_size = self.serialized_size(compressed)
            if final_size > max_chars:
                raise ContextBudgetExceeded(
                    f"required {role} context metadata exceeds character budget"
                )
        return compressed

    @staticmethod
    def serialized_size(snapshot: ContextSnapshot) -> int:
        payload = snapshot.to_dict()
        payload.pop("original_problem", None)
        payload.pop("raw_context_ref", None)
        payload["context_snapshot_id"] = snapshot.snapshot_id
        return len(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
        )

    @staticmethod
    def _dependency_closure(graph: dict[str, list[str]], roots: list[str]) -> set[str]:
        closure: set[str] = set()
        stack = [
            graph_key
            for root in roots
            for graph_key in (
                [root]
                if root in graph
                else [
                    key
                    for key in graph
                    if key.rsplit("::", 1)[-1] == root
                ]
            )
        ]
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
        if role != "RepairAgent":
            snapshot.claim_graph = {}
        for candidate in snapshot.candidates:
            for key in (
                "parse_status",
                "version",
                "unresolved_obligations",
                "is_method_duplicate",
            ):
                candidate.pop(key, None)

    def _trim_token_content(
        self,
        snapshot: ContextSnapshot,
        role: str,
        max_tokens: int,
    ) -> None:
        # Character trimming is intentionally followed by a token-level pass;
        # CJK and LaTeX have materially different token/character ratios.
        # Keep the immutable problem/conditions, hard evidence, required
        # obligations and final answer while dropping optional context.
        if self._token_counter.count_text(self._prompt_text(snapshot)).tokens <= max_tokens:
            return
        snapshot.evidence = [
            record for record in snapshot.evidence if record.get("strength") == "hard"
        ]
        snapshot.obligations = [
            obligation
            for obligation in snapshot.obligations
            if obligation.get("required", True)
        ]
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
        if role != "RepairAgent":
            snapshot.claim_graph = {}
        for candidate in snapshot.candidates:
            for key in (
                "claims",
                "method_steps",
                "public_solution_steps",
                "theorems",
                "assumptions",
            ):
                if key in candidate and isinstance(candidate[key], list):
                    candidate[key] = candidate[key][:8]
            candidate.pop("solution_text", None)
            candidate.pop("private_solution_steps", None)

    @staticmethod
    def _prompt_text(snapshot: ContextSnapshot) -> str:
        payload = snapshot.to_dict()
        payload.pop("original_problem", None)
        payload.pop("raw_context_ref", None)
        payload["context_snapshot_id"] = snapshot.snapshot_id
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)

    @staticmethod
    def _core_text(snapshot: ContextSnapshot) -> str:
        payload = {
            "original_problem": snapshot.original_problem,
            "conditions": list(snapshot.conditions),
            "problem_condition_envelope": snapshot.metadata.get(
                "problem_condition_envelope",
                {},
            ),
            "final_answer": snapshot.final_answer,
            "hard_evidence": [
                record for record in snapshot.evidence
                if record.get("strength") == "hard"
            ],
            "required_obligations": [
                obligation for obligation in snapshot.obligations
                if obligation.get("required", True)
            ],
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
