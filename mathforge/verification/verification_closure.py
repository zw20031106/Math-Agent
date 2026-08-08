from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from mathforge.harness.schemas import CandidateSolution, ProofObligation
from mathforge.verification.peer_review import PeerReviewRecord


_FINDING_STATUSES = frozenset({"pass", "fail", "unknown"})
_FINDING_SCOPES = frozenset({"local", "global", "review"})
_ACTIONS = frozenset(
    {
        "retain",
        "local_repair",
        "new_branch",
        "replan",
        "reject",
        "continue_review",
    }
)
_AUDIT_STATUSES = frozenset(
    {"complete_hard", "complete_audited", "incomplete", "failed"}
)


def _string_tuple(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a string list")
    return tuple(item for item in value if item.strip())


@dataclass(frozen=True)
class CritiqueFinding:
    finding_id: str
    candidate_id: str
    claim_id: str
    obligation_ids: tuple[str, ...]
    peer_finding_ids: tuple[str, ...]
    status: str
    scope: str
    actionability: str
    public_rationale: str
    missing_condition: str
    counterexample_summary: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["obligation_ids"] = list(self.obligation_ids)
        payload["peer_finding_ids"] = list(self.peer_finding_ids)
        return payload


@dataclass(frozen=True)
class PeerReviewAssessment:
    finding_id: str
    status: str
    public_rationale: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class CritiqueRecord:
    critique_id: str
    source_turn_id: str
    findings: tuple[CritiqueFinding, ...]
    peer_review_assessments: tuple[PeerReviewAssessment, ...]
    uncovered_goal_ids: tuple[str, ...]
    recommended_action: str
    stop_reason: str
    artifact_id: str = ""
    message_id: str = ""
    thread_id: str = ""

    @classmethod
    def from_model_payload(
        cls,
        payload: dict[str, Any],
        *,
        critique_id: str,
        source_turn_id: str,
        candidates: list[CandidateSolution],
        obligations: dict[str, list[ProofObligation]],
        peer_reviews: list[PeerReviewRecord],
    ) -> "CritiqueRecord":
        expected = {
            "findings",
            "peer_review_assessments",
            "uncovered_goal_ids",
            "recommended_action",
            "stop_reason",
        }
        if not isinstance(payload, dict) or set(payload) != expected:
            raise ValueError("Critique result fields do not match the schema")
        candidate_by_id = {item.candidate_id: item for item in candidates}
        obligation_ids = {
            candidate_id: {item.obligation_id for item in items}
            for candidate_id, items in obligations.items()
        }
        finding_counts: dict[str, int] = {}
        for review in peer_reviews:
            for finding in review.finding_items:
                finding_counts[finding.finding_id] = (
                    finding_counts.get(finding.finding_id, 0) + 1
                )
        peer_finding_ids = {
            (
                finding.finding_id
                if finding_counts[finding.finding_id] == 1
                else f"{review.review_id}:{finding.finding_id}"
            )
            for review in peer_reviews
            for finding in review.finding_items
        }
        raw_findings = payload["findings"]
        if not isinstance(raw_findings, list) or not raw_findings:
            raise ValueError("Critique requires at least one Finding")
        finding_fields = {
            "finding_id",
            "candidate_id",
            "claim_id",
            "obligation_ids",
            "peer_finding_ids",
            "status",
            "scope",
            "actionability",
            "public_rationale",
            "missing_condition",
            "counterexample_summary",
        }
        findings: list[CritiqueFinding] = []
        seen: set[str] = set()
        for item in raw_findings:
            if not isinstance(item, dict) or set(item) != finding_fields:
                raise ValueError("CritiqueFinding fields do not match the schema")
            finding_id = str(item["finding_id"]).strip()
            candidate_id = str(item["candidate_id"]).strip()
            claim_id = str(item["claim_id"]).strip()
            status = str(item["status"]).strip().casefold()
            scope = str(item["scope"]).strip().casefold()
            actionability = str(item["actionability"]).strip().casefold()
            candidate = candidate_by_id.get(candidate_id)
            if not finding_id or finding_id in seen or candidate is None:
                raise ValueError("Critique Finding identity is invalid")
            if claim_id and claim_id not in {claim.claim_id for claim in candidate.claims}:
                raise ValueError("Critique Finding Claim reference is invalid")
            own_obligations = _string_tuple(item["obligation_ids"], "obligation_ids")
            peer_ids = _string_tuple(item["peer_finding_ids"], "peer_finding_ids")
            if not set(own_obligations) <= obligation_ids.get(candidate_id, set()):
                raise ValueError("Critique Finding obligation reference is invalid")
            if not set(peer_ids) <= peer_finding_ids:
                raise ValueError("Critique peer Finding reference is invalid")
            if status not in _FINDING_STATUSES or scope not in _FINDING_SCOPES:
                raise ValueError("Critique status or scope is invalid")
            if actionability not in _ACTIONS:
                raise ValueError("Critique actionability is invalid")
            if scope == "local" and status == "fail" and not claim_id:
                raise ValueError("Local failure must cite a real Claim")
            if scope == "global" and actionability == "local_repair":
                raise ValueError("Global failure cannot be classified as a local repair")
            rationale = str(item["public_rationale"]).strip()
            if not rationale:
                raise ValueError("Critique public rationale is required")
            seen.add(finding_id)
            findings.append(
                CritiqueFinding(
                    finding_id,
                    candidate_id,
                    claim_id,
                    own_obligations,
                    peer_ids,
                    status,
                    scope,
                    actionability,
                    rationale,
                    str(item["missing_condition"]).strip(),
                    str(item["counterexample_summary"]).strip(),
                )
            )
        raw_assessments = payload["peer_review_assessments"]
        if not isinstance(raw_assessments, list):
            raise ValueError("peer_review_assessments must be a list")
        assessments: list[PeerReviewAssessment] = []
        assessed: set[str] = set()
        for item in raw_assessments:
            if not isinstance(item, dict) or set(item) != {
                "finding_id",
                "status",
                "public_rationale",
            }:
                raise ValueError("Peer Review assessment fields do not match the schema")
            finding_id = str(item["finding_id"]).strip()
            status = str(item["status"]).strip().casefold()
            rationale = str(item["public_rationale"]).strip()
            if (
                finding_id not in peer_finding_ids
                or finding_id in assessed
                or status not in _FINDING_STATUSES
                or not rationale
            ):
                raise ValueError("Peer Review assessment is invalid")
            assessed.add(finding_id)
            assessments.append(PeerReviewAssessment(finding_id, status, rationale))
        if peer_finding_ids and assessed != peer_finding_ids:
            raise ValueError("Verifier must assess every supplied Peer Review Finding")
        action = str(payload["recommended_action"]).strip().casefold()
        stop_reason = str(payload["stop_reason"]).strip()
        if action not in _ACTIONS or not stop_reason:
            raise ValueError("Critique action or stop reason is invalid")
        return cls(
            critique_id,
            source_turn_id,
            tuple(findings),
            tuple(assessments),
            _string_tuple(payload["uncovered_goal_ids"], "uncovered_goal_ids"),
            action,
            stop_reason,
        )

    def actionable_claims(self) -> dict[str, list[str]]:
        result: dict[str, set[str]] = {}
        for finding in self.findings:
            if (
                finding.status == "fail"
                and finding.actionability == "local_repair"
                and finding.claim_id
            ):
                result.setdefault(finding.candidate_id, set()).add(finding.claim_id)
        return {key: sorted(value) for key, value in result.items()}

    @property
    def requires_new_branch(self) -> bool:
        return self.recommended_action in {"new_branch", "replan"} or any(
            item.status == "fail"
            and item.actionability in {"new_branch", "replan"}
            for item in self.findings
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "critique_id": self.critique_id,
            "source_turn_id": self.source_turn_id,
            "findings": [item.to_dict() for item in self.findings],
            "peer_review_assessments": [
                item.to_dict() for item in self.peer_review_assessments
            ],
            "uncovered_goal_ids": list(self.uncovered_goal_ids),
            "recommended_action": self.recommended_action,
            "stop_reason": self.stop_reason,
            "artifact_id": self.artifact_id,
            "message_id": self.message_id,
            "thread_id": self.thread_id,
        }


@dataclass(frozen=True)
class AuditRecord:
    audit_id: str
    source_turn_id: str
    candidate_id: str
    candidate_version: int
    status: str
    open_finding_ids: tuple[str, ...]
    open_obligation_ids: tuple[str, ...]
    reviewed_artifact_ids: tuple[str, ...]
    requested_action: str
    public_rationale: str
    stop_reason: str
    artifact_id: str = ""
    message_id: str = ""
    thread_id: str = ""

    @classmethod
    def from_model_payload(
        cls,
        payload: dict[str, Any],
        *,
        audit_id: str,
        source_turn_id: str,
        candidate: CandidateSolution,
        valid_finding_ids: set[str],
        valid_obligation_ids: set[str],
        allowed_artifact_ids: set[str],
    ) -> "AuditRecord":
        expected = {
            "candidate_id",
            "candidate_version",
            "status",
            "open_finding_ids",
            "open_obligation_ids",
            "reviewed_artifact_ids",
            "requested_action",
            "public_rationale",
            "stop_reason",
        }
        if not isinstance(payload, dict) or set(payload) != expected:
            raise ValueError("Audit result fields do not match the schema")
        if str(payload["candidate_id"]).strip() != candidate.candidate_id:
            raise ValueError("Audit Candidate reference is invalid")
        if type(payload["candidate_version"]) is not int or payload["candidate_version"] != candidate.version:
            raise ValueError("Audit Candidate version is invalid")
        status = str(payload["status"]).strip().casefold()
        action = str(payload["requested_action"]).strip().casefold()
        findings = _string_tuple(payload["open_finding_ids"], "open_finding_ids")
        obligations = _string_tuple(payload["open_obligation_ids"], "open_obligation_ids")
        artifacts = _string_tuple(payload["reviewed_artifact_ids"], "reviewed_artifact_ids")
        if status not in _AUDIT_STATUSES or action not in _ACTIONS:
            raise ValueError("Audit status or requested action is invalid")
        if not set(findings) <= valid_finding_ids:
            raise ValueError("Audit Finding reference is invalid")
        if not set(obligations) <= valid_obligation_ids:
            raise ValueError("Audit obligation reference is invalid")
        if not set(artifacts) <= allowed_artifact_ids:
            raise ValueError("Audit Artifact reference is invalid")
        if status.startswith("complete_") and (findings or obligations):
            raise ValueError("Complete audit cannot retain open items")
        rationale = str(payload["public_rationale"]).strip()
        stop_reason = str(payload["stop_reason"]).strip()
        if not rationale or not stop_reason:
            raise ValueError("Audit rationale and stop reason are required")
        return cls(
            audit_id,
            source_turn_id,
            candidate.candidate_id,
            candidate.version,
            status,
            findings,
            obligations,
            artifacts,
            action,
            rationale,
            stop_reason,
        )

    @property
    def complete(self) -> bool:
        return self.status in {"complete_hard", "complete_audited"}

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for name in (
            "open_finding_ids",
            "open_obligation_ids",
            "reviewed_artifact_ids",
        ):
            payload[name] = list(payload[name])
        return payload
