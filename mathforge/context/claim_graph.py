from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from mathforge.harness.schemas import (
    CORE_SCHEMA_VERSION,
    CandidateSolution,
    SchemaValidationError,
)


_SEPARATOR = "::"


def namespaced_claim_id(candidate_id: str, claim_id: str) -> str:
    return f"{candidate_id}{_SEPARATOR}{claim_id}"


@dataclass(frozen=True)
class ClaimGraph:
    """Validated claim dependencies keyed by stable candidate namespaces."""

    SCHEMA_VERSION: ClassVar[str] = CORE_SCHEMA_VERSION

    nodes: dict[str, list[str]]
    schema_version: str = CORE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "nodes",
            {
                str(key): [str(item) for item in dependencies]
                for key, dependencies in self.nodes.items()
            },
        )
        self.validate()

    @classmethod
    def from_candidate(cls, candidate: CandidateSolution) -> "ClaimGraph":
        return cls.from_candidates([candidate])

    @classmethod
    def from_candidates(
        cls,
        candidates: list[CandidateSolution],
    ) -> "ClaimGraph":
        nodes: dict[str, list[str]] = {}
        for candidate in candidates:
            candidate.validate()
            for claim in candidate.claims:
                key = namespaced_claim_id(candidate.candidate_id, claim.claim_id)
                if key in nodes:
                    raise SchemaValidationError(f"duplicate namespaced claim id: {key}")
                nodes[key] = [
                    namespaced_claim_id(candidate.candidate_id, dependency)
                    for dependency in claim.depends_on
                ]
        return cls(nodes)

    def validate(self) -> None:
        if self.schema_version != self.SCHEMA_VERSION:
            raise SchemaValidationError("invalid ClaimGraph schema version")
        if not isinstance(self.nodes, dict):
            raise SchemaValidationError("ClaimGraph.nodes must be an object")
        for claim_id, dependencies in self.nodes.items():
            if _SEPARATOR not in claim_id:
                raise SchemaValidationError(
                    f"claim graph key is not namespaced: {claim_id}"
                )
            if not isinstance(dependencies, list) or any(
                not isinstance(item, str) for item in dependencies
            ):
                raise SchemaValidationError(
                    f"claim graph dependencies must be strings: {claim_id}"
                )
            if claim_id in dependencies:
                raise SchemaValidationError(
                    f"self dependency in claim graph: {claim_id}"
                )
            unknown = set(dependencies) - set(self.nodes)
            if unknown:
                raise SchemaValidationError(
                    f"unknown claim graph dependencies for {claim_id}: {sorted(unknown)}"
                )

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(claim_id: str) -> None:
            if claim_id in visiting:
                raise SchemaValidationError("claim graph dependency cycle")
            if claim_id in visited:
                return
            visiting.add(claim_id)
            for dependency in self.nodes[claim_id]:
                visit(dependency)
            visiting.remove(claim_id)
            visited.add(claim_id)

        for claim_id in self.nodes:
            visit(claim_id)

    def dependency_closure(self, claim_ids: list[str]) -> list[str]:
        closure: set[str] = set()
        stack = list(claim_ids)
        while stack:
            claim_id = stack.pop()
            if claim_id in closure or claim_id not in self.nodes:
                continue
            closure.add(claim_id)
            stack.extend(self.nodes[claim_id])
        return sorted(closure)

    def terminal_claim_ids(self, candidate_id: str) -> list[str]:
        prefix = f"{candidate_id}{_SEPARATOR}"
        own = {claim_id for claim_id in self.nodes if claim_id.startswith(prefix)}
        depended_on = {
            dependency
            for claim_id, dependencies in self.nodes.items()
            if claim_id.startswith(prefix)
            for dependency in dependencies
        }
        return sorted(own - depended_on)

    def to_nodes_dict(self) -> dict[str, list[str]]:
        return {
            claim_id: list(dependencies)
            for claim_id, dependencies in sorted(self.nodes.items())
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "nodes": self.to_nodes_dict(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ClaimGraph":
        if not isinstance(payload, dict):
            raise SchemaValidationError("ClaimGraph payload must be an object")
        if set(payload) != {"schema_version", "nodes"}:
            raise SchemaValidationError("ClaimGraph fields are invalid")
        if payload.get("schema_version") != cls.SCHEMA_VERSION:
            raise SchemaValidationError("invalid ClaimGraph schema version")
        raw_nodes = payload.get("nodes")
        if not isinstance(raw_nodes, dict):
            raise SchemaValidationError("ClaimGraph.nodes must be an object")
        graph = cls(
            {
                str(key): list(value) if isinstance(value, list) else value
                for key, value in raw_nodes.items()
            },
            schema_version=cls.SCHEMA_VERSION,
        )
        graph.validate()
        return graph
