from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from hashlib import sha256
import json
import re
from typing import Any

from mathforge.harness.schemas import CandidateSolution
from mathforge.verification.answer_normalization import canonical_answer
from mathforge.verification.review_repair_audit_v2 import classify_concession


_CANDIDATE_STATES = frozenset(
    {
        "draft",
        "submitted",
        "peer_reviewing",
        "challenged",
        "rebutted",
        "repair_requested",
        "revised",
        "verified",
        "incomplete",
        "rejected",
        "superseded",
        "selected",
    }
)


def _normalized(value: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", str(value).casefold()).split())


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


@dataclass(frozen=True)
class MethodSignature:
    method_family: str
    representation: str
    core_invariant: str
    proof_direction: str
    claim_topology_sha256: str

    @classmethod
    def from_candidate(cls, candidate: CandidateSolution) -> "MethodSignature":
        method_family = candidate.planned_method_family or candidate.method
        step_kinds = [step.kind for step in candidate.method_steps]
        claim_kinds = [claim.claim_kind for claim in candidate.claims]
        representation = _normalized(
            " ".join(
                (
                    method_family,
                    candidate.method,
                    *step_kinds[:8],
                    *claim_kinds[:8],
                )
            )
        )
        critical = [
            _normalized(claim.statement)
            for claim in candidate.claims
            if claim.importance == "critical" and claim.statement.strip()
        ]
        if not critical:
            critical = [
                _normalized(claim.statement)
                for claim in candidate.claims[:4]
                if claim.statement.strip()
            ]
        core_invariant = _digest(critical)[:16]
        topology = [
            {
                "importance": claim.importance,
                "check_type": claim.check_type,
                "dependency_count": len(claim.depends_on),
            }
            for claim in candidate.claims
        ]
        proof_direction = "->".join(step_kinds) or "dependency-forward"
        return cls(
            method_family=_normalized(method_family),
            representation=representation,
            core_invariant=core_invariant,
            proof_direction=proof_direction,
            claim_topology_sha256=_digest(topology),
        )

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class IndependenceAssessment:
    independent: bool
    score: int
    reason_codes: tuple[str, ...]
    compared_candidate_id: str = ""
    execution_independence: bool = True
    method_independence: bool = True
    context_independence: bool = True
    evidence_independence: bool = True
    prompt_independence: bool = True
    skill_independence: bool = True
    model_independence: bool = True
    lemma_independence: bool = True
    correlated_corroboration: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reason_codes"] = list(self.reason_codes)
        return payload


@dataclass(frozen=True)
class CandidatePoolEntry:
    candidate_id: str
    author_agent_id: str
    source_turn_id: str
    candidate_artifact_id: str
    method_signature: MethodSignature
    version: int
    parent_candidate_id: str = ""
    status: str = "submitted"
    independent: bool = True
    duplicate_of: str = ""
    independence_score: int = 4
    independence_reason_codes: tuple[str, ...] = ()
    peer_review_ids: tuple[str, ...] = ()
    review_incomplete: bool = False
    rebuttal_ids: tuple[str, ...] = ()
    conceded_finding_ids: tuple[str, ...] = ()
    branch_id: str = ""
    plan_id: str = ""
    plan_version: int = 0
    skill_set_hash: str = ""
    shared_context_hash: str = ""
    branch_context_hash: str = ""
    lemma_ids: tuple[str, ...] = ()
    tool_evidence_refs: tuple[str, ...] = ()
    execution_independence: bool = True
    method_independence: bool = True
    context_independence: bool = True
    evidence_independence: bool = True
    prompt_hash: str = ""
    model_identity: str = ""
    prompt_independence: bool = True
    skill_independence: bool = True
    model_independence: bool = True
    lemma_independence: bool = True
    correlated_corroboration: bool = False

    def __post_init__(self) -> None:
        if self.status not in _CANDIDATE_STATES:
            raise ValueError("invalid CandidatePool state")
        if not self.candidate_id or not self.author_agent_id:
            raise ValueError("candidate and author identities are required")
        if not self.source_turn_id or not self.candidate_artifact_id:
            raise ValueError("candidate publication lineage is required")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["method_signature"] = self.method_signature.to_dict()
        for name in (
            "independence_reason_codes",
            "peer_review_ids",
            "rebuttal_ids",
            "conceded_finding_ids",
            "lemma_ids",
            "tool_evidence_refs",
        ):
            payload[name] = list(payload[name])
        return payload


class CandidatePool:
    """Per-problem immutable-version candidate registry and independence gate."""

    def __init__(self) -> None:
        self._entries: dict[str, CandidatePoolEntry] = {}
        self._candidates: dict[str, CandidateSolution] = {}

    def submit(
        self,
        candidate: CandidateSolution,
        *,
        author_agent_id: str,
        source_turn_id: str,
        candidate_artifact_id: str,
        provenance: dict[str, Any] | None = None,
    ) -> CandidatePoolEntry:
        if candidate.candidate_id in self._entries:
            raise ValueError("candidate version is already registered")
        provenance = dict(provenance or {})
        signature = MethodSignature.from_candidate(candidate)
        assessment = self._assess(
            candidate,
            signature,
            author_agent_id,
            source_turn_id,
            provenance,
        )
        # CandidatePool is the Host-owned independence authority.  Reflect
        # that decision on the candidate consumed by arbitration so a
        # correlated answer cannot later be counted as independent agreement.
        candidate.is_method_duplicate = bool(
            candidate.is_method_duplicate or not assessment.independent
        )
        entry = CandidatePoolEntry(
            candidate_id=candidate.candidate_id,
            author_agent_id=author_agent_id,
            source_turn_id=source_turn_id,
            candidate_artifact_id=candidate_artifact_id,
            method_signature=signature,
            version=candidate.version,
            status="submitted",
            independent=assessment.independent,
            duplicate_of=(
                "" if assessment.independent else assessment.compared_candidate_id
            ),
            independence_score=assessment.score,
            independence_reason_codes=assessment.reason_codes,
            branch_id=str(provenance.get("branch_id", candidate.candidate_id)),
            plan_id=str(provenance.get("plan_id", "")),
            plan_version=int(provenance.get("plan_version", 0)),
            skill_set_hash=str(provenance.get("skill_set_hash", "")),
            shared_context_hash=str(provenance.get("shared_context_hash", "")),
            branch_context_hash=str(provenance.get("branch_context_hash", "")),
            lemma_ids=tuple(str(item) for item in provenance.get("lemma_ids", ())),
            tool_evidence_refs=tuple(
                str(item) for item in provenance.get("tool_evidence_refs", ())
            ),
            execution_independence=assessment.execution_independence,
            method_independence=assessment.method_independence,
            context_independence=assessment.context_independence,
            evidence_independence=assessment.evidence_independence,
            prompt_hash=str(provenance.get("prompt_hash", "")),
            model_identity=str(provenance.get("model_identity", "")),
            prompt_independence=assessment.prompt_independence,
            skill_independence=assessment.skill_independence,
            model_independence=assessment.model_independence,
            lemma_independence=assessment.lemma_independence,
            correlated_corroboration=assessment.correlated_corroboration,
        )
        self._entries[candidate.candidate_id] = entry
        self._candidates[candidate.candidate_id] = deepcopy(candidate)
        return entry

    def _assess(
        self,
        candidate: CandidateSolution,
        signature: MethodSignature,
        author_agent_id: str,
        source_turn_id: str,
        provenance: dict[str, Any],
    ) -> IndependenceAssessment:
        if not self._entries:
            return IndependenceAssessment(True, 4, ("first_candidate",))
        for other_id, other in self._entries.items():
            other_candidate = self._candidates[other_id]
            reasons: list[str] = []
            score = 0
            if author_agent_id != other.author_agent_id:
                score += 1
            else:
                reasons.append("same_author_agent")
            if source_turn_id != other.source_turn_id:
                score += 1
            else:
                reasons.append("same_model_turn")
            if signature.method_family != other.method_signature.method_family:
                score += 1
            else:
                reasons.append("same_method_family")
            structural_same = sum(
                (
                    signature.representation
                    == other.method_signature.representation,
                    signature.core_invariant
                    == other.method_signature.core_invariant,
                    signature.proof_direction
                    == other.method_signature.proof_direction,
                    signature.claim_topology_sha256
                    == other.method_signature.claim_topology_sha256,
                )
            )
            same_answer = canonical_answer(
                candidate.final_answer,
                candidate.answer_type,
            ) == canonical_answer(
                other_candidate.final_answer,
                other_candidate.answer_type,
            )
            if structural_same < 3:
                score += 1
            elif same_answer:
                reasons.append("semantic_candidate_duplicate")
            execution_independence = (
                author_agent_id != other.author_agent_id
                and source_turn_id != other.source_turn_id
            )
            method_independence = (
                signature.method_family != other.method_signature.method_family
                and structural_same < 3
            )
            shared_context_hash = str(provenance.get("shared_context_hash", ""))
            branch_context_hash = str(provenance.get("branch_context_hash", ""))
            if branch_context_hash and other.branch_context_hash:
                context_independence = (
                    branch_context_hash != other.branch_context_hash
                )
            else:
                context_independence = not (
                    shared_context_hash
                    and shared_context_hash == other.shared_context_hash
                )
            evidence_refs = {
                str(item) for item in provenance.get("tool_evidence_refs", ())
            }
            evidence_independence = not bool(
                evidence_refs.intersection(other.tool_evidence_refs)
            )
            prompt_hash = str(provenance.get("prompt_hash", ""))
            prompt_independence = bool(
                prompt_hash
                and other.prompt_hash
                and prompt_hash != other.prompt_hash
            )
            if not prompt_independence:
                reasons.append(
                    "missing_prompt_hash"
                    if not prompt_hash or not other.prompt_hash
                    else "same_prompt_hash"
                )
            skill_hash = str(provenance.get("skill_set_hash", ""))
            skill_independence = not (
                skill_hash
                and other.skill_set_hash
                and skill_hash == other.skill_set_hash
                and signature.method_family == other.method_signature.method_family
            )
            if not skill_independence:
                reasons.append("same_skill_set_and_method")
            model_identity = str(provenance.get("model_identity", ""))
            model_independence = bool(
                model_identity
                and other.model_identity
                and (
                    model_identity != other.model_identity
                    or prompt_independence
                    or context_independence
                )
            )
            if not model_independence:
                reasons.append(
                    "missing_model_identity"
                    if not model_identity or not other.model_identity
                    else "same_model_same_execution_context"
                )
            lemma_ids = {
                str(item) for item in provenance.get("lemma_ids", ())
            }
            lemma_independence = not (
                lemma_ids
                and set(other.lemma_ids)
                and lemma_ids == set(other.lemma_ids)
            )
            if not lemma_independence:
                reasons.append("same_lemma_disclosure")
            correlated_corroboration = bool(
                model_identity
                and model_identity == other.model_identity
                and same_answer
            )
            if correlated_corroboration:
                reasons.append("correlated_same_model_answer")
            independent = all(
                (
                    execution_independence,
                    method_independence,
                    context_independence,
                    evidence_independence,
                    prompt_independence,
                    skill_independence,
                    model_independence,
                    lemma_independence,
                )
            )
            if not independent:
                return IndependenceAssessment(
                    False,
                    score,
                    tuple(dict.fromkeys(reasons)),
                    other_id,
                    execution_independence,
                    method_independence,
                    context_independence,
                    evidence_independence,
                    prompt_independence,
                    skill_independence,
                    model_independence,
                    lemma_independence,
                    correlated_corroboration,
                )
        return IndependenceAssessment(
            True,
            4,
            ("structurally_distinct",),
            correlated_corroboration=False,
        )

    def mark_peer_reviewing(self, candidate_id: str) -> CandidatePoolEntry:
        return self._update(candidate_id, status="peer_reviewing")

    def mark_review_incomplete(self, candidate_id: str) -> CandidatePoolEntry:
        """Record a review gap without fabricating reviewed status.

        A failed reviewer turn must not make a candidate look reviewed, but it
        also must not erase a candidate that already has a valid review.  A
        candidate with no attached review returns to ``submitted`` so the
        deterministic arbitration layer can decide using the evidence it has;
        ``review_incomplete`` and the coverage projection expose the gap.
        """

        entry = self._entries[candidate_id]
        status = entry.status if entry.peer_review_ids else "submitted"
        return self._update(
            candidate_id,
            status=status,
            review_incomplete=True,
        )

    def attach_review(
        self,
        candidate_id: str,
        review_id: str,
        *,
        challenged: bool,
    ) -> CandidatePoolEntry:
        entry = self._entries[candidate_id]
        return self._update(
            candidate_id,
            status="challenged" if challenged else "peer_reviewing",
            peer_review_ids=tuple(dict.fromkeys((*entry.peer_review_ids, review_id))),
        )

    def attach_rebuttal(
        self,
        candidate_id: str,
        rebuttal_id: str,
        *,
        conceded_finding_ids: tuple[str, ...] = (),
        finding_severities: dict[str, str] | None = None,
        finding_scopes: dict[str, str] | None = None,
        confirmed_finding_ids: tuple[str, ...] = (),
    ) -> CandidatePoolEntry:
        entry = self._entries[candidate_id]
        conceded = tuple(
            dict.fromkeys((*entry.conceded_finding_ids, *conceded_finding_ids))
        )
        severities = {
            finding_id: str((finding_severities or {}).get(finding_id, "warning"))
            for finding_id in conceded_finding_ids
        }
        dispositions = [
            classify_concession(
                severity,
                scope=str((finding_scopes or {}).get(finding_id, "local")),
                confirmed=finding_id in set(confirmed_finding_ids),
            )
            for finding_id, severity in severities.items()
        ]
        status = "rebutted"
        if any(item.candidate_status == "rejected" for item in dispositions):
            status = "rejected"
        elif any(
            item.candidate_status == "repair_requested" for item in dispositions
        ):
            status = "repair_requested"
        elif dispositions:
            status = "challenged"
        return self._update(
            candidate_id,
            status=status,
            rebuttal_ids=tuple(dict.fromkeys((*entry.rebuttal_ids, rebuttal_id))),
            conceded_finding_ids=conceded,
        )

    def reject(self, candidate_id: str) -> CandidatePoolEntry:
        return self._update(candidate_id, status="rejected")

    def _update(self, candidate_id: str, **changes: Any) -> CandidatePoolEntry:
        entry = replace(self._entries[candidate_id], **changes)
        self._entries[candidate_id] = entry
        return entry

    def entry(self, candidate_id: str) -> CandidatePoolEntry:
        return self._entries[candidate_id]

    def independent_entries(self) -> tuple[CandidatePoolEntry, ...]:
        return tuple(
            entry
            for entry in self._entries.values()
            if entry.independent and entry.status != "rejected"
        )

    def viable_entries(self) -> tuple[CandidatePoolEntry, ...]:
        return tuple(
            entry
            for entry in self._entries.values()
            if entry.status not in {"rejected", "superseded", "incomplete"}
        )

    def active_candidate_ids(self) -> tuple[str, ...]:
        return tuple(
            entry.candidate_id
            for entry in self._entries.values()
            if entry.status not in {"rejected", "superseded", "incomplete"}
        )

    def snapshot(self) -> list[dict[str, Any]]:
        return [entry.to_dict() for entry in self._entries.values()]

    def review_coverage(self) -> dict[str, dict[str, Any]]:
        """Return explicit per-candidate review coverage, including gaps."""

        return {
            candidate_id: {
                "reviewed": bool(entry.peer_review_ids),
                "review_incomplete": entry.review_incomplete,
                "review_count": len(entry.peer_review_ids),
                "review_ids": list(entry.peer_review_ids),
                "status": entry.status,
            }
            for candidate_id, entry in self._entries.items()
        }


@dataclass
class ReviewThreadGuard:
    """Stops circular review replies that add no new public content."""

    thread_id: str
    payload_hashes: set[str] = field(default_factory=set)
    status: str = "open"

    def record(self, payload: dict[str, Any]) -> bool:
        if self.status != "open":
            return False
        digest = _digest(payload)
        if digest in self.payload_hashes:
            self.status = "closed"
            return False
        self.payload_hashes.add(digest)
        return True

    def close(self) -> None:
        self.status = "closed"

    def reopen(self, payload: dict[str, Any]) -> bool:
        digest = _digest(payload)
        if digest in self.payload_hashes:
            return False
        self.status = "open"
        self.payload_hashes.add(digest)
        return True
