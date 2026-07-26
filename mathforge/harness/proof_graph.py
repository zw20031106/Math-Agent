from __future__ import annotations

from typing import Any, Iterable

from mathforge.harness.schemas import (
    CandidateSolution,
    EvidenceRecord,
    ProofObligation,
)
from mathforge.verification.evidence import is_fatal_hard_failure


PROOF_GRAPH_SCHEMA_VERSION = "1.0"


def build_claim_evidence_graph(
    candidates: Iterable[CandidateSolution],
    evidence: Iterable[EvidenceRecord],
    proof_obligations: dict[str, list[ProofObligation]],
    *,
    candidate_states: Iterable[dict[str, Any]] = (),
    selected_candidate_id: str = "",
) -> dict[str, Any]:
    """Build the public, deterministic Claim—Evidence graph for one solve."""

    candidate_items = list(candidates)
    evidence_items = list(evidence)
    state_by_id = {
        str(item.get("candidate_id", "")): item
        for item in candidate_states
        if isinstance(item, dict) and item.get("candidate_id")
    }
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []

    for candidate in sorted(candidate_items, key=lambda item: item.candidate_id):
        candidate_node_id = _candidate_node_id(candidate.candidate_id)
        state = state_by_id.get(candidate.candidate_id, {})
        nodes.append(
            {
                "id": candidate_node_id,
                "kind": "candidate",
                "candidate_id": candidate.candidate_id,
                "role": candidate.role,
                "method": candidate.method,
                "version": candidate.version,
                "status": str(state.get("status", "generated")),
                "complete": bool(
                    candidate.final_answer.strip()
                    and candidate.public_solution_steps
                    and candidate.claims
                ),
                "final_answer": candidate.final_answer,
                "selected": candidate.candidate_id == selected_candidate_id,
            }
        )
        for claim in sorted(candidate.claims, key=lambda item: item.claim_id):
            claim_node_id = _claim_node_id(candidate.candidate_id, claim.claim_id)
            nodes.append(
                {
                    "id": claim_node_id,
                    "kind": "claim",
                    "candidate_id": candidate.candidate_id,
                    "claim_id": claim.claim_id,
                    "statement": claim.statement,
                    "importance": claim.importance,
                    "claim_kind": claim.claim_kind,
                    "status": claim.status,
                    "verification_state": claim.verification_state,
                }
            )
            edges.append(
                _edge(
                    candidate_node_id,
                    claim_node_id,
                    "candidate_has_claim",
                )
            )
            for dependency in sorted(set(claim.depends_on)):
                edges.append(
                    _edge(
                        _claim_node_id(candidate.candidate_id, dependency),
                        claim_node_id,
                        "claim_supports_claim",
                    )
                )

    for record in sorted(evidence_items, key=lambda item: item.evidence_id):
        evidence_node_id = _evidence_node_id(record.evidence_id)
        nodes.append(
            {
                "id": evidence_node_id,
                "kind": "evidence",
                "evidence_id": record.evidence_id,
                "candidate_id": record.candidate_id,
                "claim_id": record.claim_id,
                "evidence_type": record.evidence_type,
                "capability": record.capability,
                "status": record.status,
                "strength": record.strength,
                "transaction_status": record.transaction_status,
                "summary": record.description,
                "fatal": is_fatal_hard_failure(record),
            }
        )
        target = (
            _claim_node_id(record.candidate_id, record.claim_id)
            if record.claim_id is not None
            else _candidate_node_id(record.candidate_id)
        )
        relation = {
            "pass": "evidence_supports",
            "fail": "evidence_refutes",
        }.get(record.status, "evidence_leaves_unknown")
        edges.append(_edge(evidence_node_id, target, relation))

    for candidate_id in sorted(proof_obligations):
        for obligation in sorted(
            proof_obligations[candidate_id],
            key=lambda item: item.obligation_id,
        ):
            obligation_node_id = _obligation_node_id(obligation.obligation_id)
            nodes.append(
                {
                    "id": obligation_node_id,
                    "kind": "obligation",
                    "obligation_id": obligation.obligation_id,
                    "candidate_id": candidate_id,
                    "obligation_kind": obligation.kind,
                    "description": obligation.description,
                    "required": obligation.required,
                    "status": obligation.status,
                }
            )
            edges.append(
                _edge(
                    _candidate_node_id(candidate_id),
                    obligation_node_id,
                    "candidate_requires_obligation",
                )
            )
            for claim_id in sorted(set(obligation.source_claim_ids)):
                edges.append(
                    _edge(
                        _claim_node_id(candidate_id, claim_id),
                        obligation_node_id,
                        "claim_addresses_obligation",
                    )
                )
            for evidence_id in sorted(
                set(obligation.satisfaction_evidence_ids)
            ):
                edges.append(
                    _edge(
                        _evidence_node_id(evidence_id),
                        obligation_node_id,
                        "evidence_satisfies_obligation",
                    )
                )

    node_kinds = {
        kind: sum(node["kind"] == kind for node in nodes)
        for kind in ("candidate", "claim", "evidence", "obligation")
    }
    evidence_statuses = {
        status: sum(
            node["kind"] == "evidence" and node["status"] == status
            for node in nodes
        )
        for status in ("pass", "fail", "unknown", "error")
    }
    return {
        "schema_version": PROOF_GRAPH_SCHEMA_VERSION,
        "selected_candidate_id": selected_candidate_id,
        "nodes": nodes,
        "edges": _deduplicate_edges(edges),
        "summary": {
            "node_counts": node_kinds,
            "evidence_status_counts": evidence_statuses,
            "unresolved_required_obligations": sum(
                node["kind"] == "obligation"
                and node["required"]
                and node["status"] != "satisfied"
                for node in nodes
            ),
        },
    }


def _candidate_node_id(candidate_id: str) -> str:
    return f"candidate:{candidate_id}"


def _claim_node_id(candidate_id: str, claim_id: str) -> str:
    return f"claim:{candidate_id}:{claim_id}"


def _evidence_node_id(evidence_id: str) -> str:
    return f"evidence:{evidence_id}"


def _obligation_node_id(obligation_id: str) -> str:
    return f"obligation:{obligation_id}"


def _edge(source: str, target: str, relation: str) -> dict[str, str]:
    return {"from": source, "to": target, "relation": relation}


def _deduplicate_edges(edges: list[dict[str, str]]) -> list[dict[str, str]]:
    unique = {
        (edge["from"], edge["to"], edge["relation"])
        for edge in edges
    }
    return [
        {"from": source, "to": target, "relation": relation}
        for source, target, relation in sorted(unique)
    ]
