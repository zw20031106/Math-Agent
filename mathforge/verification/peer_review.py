from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from mathforge.harness.schemas import CandidateSolution


_FINDING_STATUSES = frozenset({"pass", "fail", "unknown"})
_SEVERITIES = frozenset({"info", "warning", "error", "critical"})
_REBUTTAL_ACTIONS = frozenset({"defend", "clarify", "concede"})


def _string_list(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a string list")
    return tuple(item for item in value if item.strip())


@dataclass(frozen=True)
class ReviewFinding:
    finding_id: str
    candidate_id: str
    claim_id: str
    method_step_id: str
    obligation_ids: tuple[str, ...]
    status: str
    public_rationale: str
    missing_condition: str
    counterexample_summary: str
    severity: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["obligation_ids"] = list(self.obligation_ids)
        return payload


@dataclass(frozen=True)
class PeerReviewRecord:
    review_id: str
    reviewer_agent_id: str
    author_agent_id: str
    candidate_id: str
    candidate_version: int
    candidate_artifact_id: str
    source_turn_id: str
    finding_items: tuple[ReviewFinding, ...]
    answer_assessment: str
    method_overlap_assessment: str
    missing_conditions: tuple[str, ...]
    counterexample_attempts: tuple[str, ...]
    unresolved_obligations: tuple[str, ...]
    recommended_action: str
    stop_reason: str
    artifact_id: str = ""
    message_id: str = ""

    @classmethod
    def from_model_payload(
        cls,
        payload: dict[str, Any],
        *,
        review_id: str,
        reviewer_agent_id: str,
        author_agent_id: str,
        candidate: CandidateSolution,
        candidate_artifact_id: str,
        source_turn_id: str,
        obligation_ids: set[str],
    ) -> "PeerReviewRecord":
        expected = {
            "finding_items",
            "answer_assessment",
            "method_overlap_assessment",
            "missing_conditions",
            "counterexample_attempts",
            "unresolved_obligations",
            "recommended_action",
            "stop_reason",
        }
        if not isinstance(payload, dict) or set(payload) != expected:
            raise ValueError("PeerReview result fields do not match the schema")
        claim_ids = {claim.claim_id for claim in candidate.claims}
        step_ids = {step.step_id for step in candidate.method_steps}
        raw_findings = payload["finding_items"]
        if not isinstance(raw_findings, list) or not raw_findings:
            raise ValueError("PeerReview requires at least one Claim-linked finding")
        findings: list[ReviewFinding] = []
        finding_ids: set[str] = set()
        fields = {
            "finding_id",
            "candidate_id",
            "claim_id",
            "method_step_id",
            "obligation_ids",
            "status",
            "public_rationale",
            "missing_condition",
            "counterexample_summary",
            "severity",
        }
        for item in raw_findings:
            if not isinstance(item, dict) or set(item) != fields:
                raise ValueError("ReviewFinding fields do not match the schema")
            finding_id = str(item["finding_id"]).strip()
            candidate_id = str(item["candidate_id"]).strip()
            claim_id = str(item["claim_id"]).strip()
            method_step_id = str(item["method_step_id"]).strip()
            status = str(item["status"]).strip().casefold()
            severity = str(item["severity"]).strip().casefold()
            references = _string_list(item["obligation_ids"], "obligation_ids")
            if not finding_id or finding_id in finding_ids:
                raise ValueError("ReviewFinding identity is missing or duplicated")
            if candidate_id != candidate.candidate_id or claim_id not in claim_ids:
                raise ValueError("ReviewFinding must cite the reviewed Candidate and a real Claim")
            if method_step_id and method_step_id not in step_ids:
                raise ValueError("ReviewFinding method step reference is invalid")
            if not set(references) <= obligation_ids:
                raise ValueError("ReviewFinding obligation reference is invalid")
            if status not in _FINDING_STATUSES or severity not in _SEVERITIES:
                raise ValueError("ReviewFinding status or severity is invalid")
            rationale = str(item["public_rationale"]).strip()
            if not rationale:
                raise ValueError("ReviewFinding public rationale is required")
            finding_ids.add(finding_id)
            findings.append(
                ReviewFinding(
                    finding_id,
                    candidate_id,
                    claim_id,
                    method_step_id,
                    references,
                    status,
                    rationale,
                    str(item["missing_condition"]).strip(),
                    str(item["counterexample_summary"]).strip(),
                    severity,
                )
            )
        strings = {
            name: str(payload[name]).strip()
            for name in (
                "answer_assessment",
                "method_overlap_assessment",
                "recommended_action",
                "stop_reason",
            )
        }
        if any(not value for value in strings.values()):
            raise ValueError("PeerReview assessments and stop reason are required")
        return cls(
            review_id=review_id,
            reviewer_agent_id=reviewer_agent_id,
            author_agent_id=author_agent_id,
            candidate_id=candidate.candidate_id,
            candidate_version=candidate.version,
            candidate_artifact_id=candidate_artifact_id,
            source_turn_id=source_turn_id,
            finding_items=tuple(findings),
            answer_assessment=strings["answer_assessment"],
            method_overlap_assessment=strings["method_overlap_assessment"],
            missing_conditions=_string_list(payload["missing_conditions"], "missing_conditions"),
            counterexample_attempts=_string_list(payload["counterexample_attempts"], "counterexample_attempts"),
            unresolved_obligations=_string_list(payload["unresolved_obligations"], "unresolved_obligations"),
            recommended_action=strings["recommended_action"],
            stop_reason=strings["stop_reason"],
        )

    @property
    def challenged(self) -> bool:
        return any(item.status != "pass" for item in self.finding_items)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["finding_items"] = [item.to_dict() for item in self.finding_items]
        for name in (
            "missing_conditions",
            "counterexample_attempts",
            "unresolved_obligations",
        ):
            payload[name] = list(payload[name])
        return payload


@dataclass(frozen=True)
class RebuttalItem:
    finding_id: str
    response: str
    action: str
    supporting_claim_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    requested_followup: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["supporting_claim_ids"] = list(self.supporting_claim_ids)
        payload["evidence_refs"] = list(self.evidence_refs)
        return payload


@dataclass(frozen=True)
class RebuttalRecord:
    rebuttal_id: str
    author_agent_id: str
    reviewer_agent_id: str
    candidate_id: str
    candidate_version: int
    review_id: str
    source_turn_id: str
    responses: tuple[RebuttalItem, ...]
    stop_reason: str
    artifact_id: str = ""
    message_id: str = ""

    @classmethod
    def from_model_payload(
        cls,
        payload: dict[str, Any],
        *,
        rebuttal_id: str,
        author_agent_id: str,
        reviewer_agent_id: str,
        candidate: CandidateSolution,
        review: PeerReviewRecord,
        source_turn_id: str,
    ) -> "RebuttalRecord":
        if not isinstance(payload, dict) or set(payload) != {"responses", "stop_reason"}:
            raise ValueError("Rebuttal result fields do not match the schema")
        raw_responses = payload["responses"]
        if not isinstance(raw_responses, list) or not raw_responses:
            raise ValueError("Rebuttal requires Finding-linked responses")
        finding_ids = {item.finding_id for item in review.finding_items}
        claim_ids = {claim.claim_id for claim in candidate.claims}
        seen: set[str] = set()
        responses: list[RebuttalItem] = []
        fields = {
            "finding_id",
            "response",
            "action",
            "supporting_claim_ids",
            "evidence_refs",
            "requested_followup",
        }
        for item in raw_responses:
            if not isinstance(item, dict) or set(item) != fields:
                raise ValueError("Rebuttal response fields do not match the schema")
            finding_id = str(item["finding_id"]).strip()
            action = str(item["action"]).strip().casefold()
            response = str(item["response"]).strip()
            supporting = _string_list(item["supporting_claim_ids"], "supporting_claim_ids")
            if finding_id not in finding_ids or finding_id in seen:
                raise ValueError("Rebuttal must cite each real Finding at most once")
            if action not in _REBUTTAL_ACTIONS or not response:
                raise ValueError("Rebuttal action or response is invalid")
            if not set(supporting) <= claim_ids:
                raise ValueError("Rebuttal supporting Claim reference is invalid")
            seen.add(finding_id)
            responses.append(
                RebuttalItem(
                    finding_id,
                    response,
                    action,
                    supporting,
                    _string_list(item["evidence_refs"], "evidence_refs"),
                    str(item["requested_followup"]).strip(),
                )
            )
        stop_reason = str(payload["stop_reason"]).strip()
        if not stop_reason:
            raise ValueError("Rebuttal stop reason is required")
        return cls(
            rebuttal_id,
            author_agent_id,
            reviewer_agent_id,
            candidate.candidate_id,
            candidate.version,
            review.review_id,
            source_turn_id,
            tuple(responses),
            stop_reason,
        )

    @property
    def conceded_finding_ids(self) -> tuple[str, ...]:
        return tuple(item.finding_id for item in self.responses if item.action == "concede")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["responses"] = [item.to_dict() for item in self.responses]
        return payload
