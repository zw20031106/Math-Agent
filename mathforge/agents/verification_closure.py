from __future__ import annotations

from dataclasses import dataclass, replace
import json

from mathforge.agent_runtime.protocol import AgentTurnPayloadParser
from mathforge.agents.prompt_compiler import PromptCompiler
from mathforge.agents.registry import PromptContractLoader
from mathforge.harness.budget import CallBudget
from mathforge.harness.errors import ModelResponseError
from mathforge.harness.provider import OfficialClientProvider
from mathforge.harness.schemas import (
    CandidateSolution,
    EvidenceRecord,
    ProblemIR,
    ProofObligation,
)
from mathforge.verification.peer_review import PeerReviewRecord, RebuttalRecord
from mathforge.verification.verification_closure import AuditRecord, CritiqueRecord


@dataclass(frozen=True)
class CrossExamOutcome:
    record: CritiqueRecord
    turn_id: str


@dataclass(frozen=True)
class FinalAuditOutcome:
    record: AuditRecord
    turn_id: str


class VerificationClosureAgent:
    """Runs normalized Cross Exam and Final Audit as independent model Turns."""

    def __init__(
        self,
        provider: OfficialClientProvider,
        contracts: PromptContractLoader | None = None,
    ) -> None:
        self._provider = provider
        self._compiler = PromptCompiler(contracts or PromptContractLoader())

    def cross_exam(
        self,
        *,
        problem: ProblemIR,
        candidates: list[CandidateSolution],
        candidate_pool: list[dict],
        obligations: dict[str, list[ProofObligation]],
        evidence: list[EvidenceRecord],
        peer_reviews: list[PeerReviewRecord],
        rebuttals: list[RebuttalRecord],
        input_artifact_ids: tuple[str, ...],
        budget: CallBudget,
        max_tokens: int,
        ordinal: int = 1,
    ) -> CrossExamOutcome:
        payload = {
            "problem": problem.normalized_problem,
            "conditions": list(problem.assumptions),
            "response_mode": problem.response_mode,
            "candidate_pool": list(candidate_pool),
            "candidates": [_public_candidate(item) for item in candidates],
            "obligations": {
                key: [item.to_dict() for item in value]
                for key, value in obligations.items()
                if key in {candidate.candidate_id for candidate in candidates}
            },
            "evidence": [
                item.to_dict()
                for item in evidence
                if item.candidate_id in {candidate.candidate_id for candidate in candidates}
                and item.transaction_status == "active"
            ],
            "peer_reviews": _public_peer_reviews(peer_reviews),
            "rebuttals": [item.to_dict() for item in rebuttals],
        }
        compilation = self._compiler.compile_verifier_closure(
            user_content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            mode="cross_exam",
        )
        response = self._call(
            compilation.messages,
            budget=budget,
            max_tokens=min(max_tokens or compilation.max_output_tokens, compilation.max_output_tokens),
            mode="cross-exam",
            ordinal=ordinal,
            action_category="verification",
            input_artifact_ids=input_artifact_ids,
        )
        parsed = self._parse(response, "challenge_candidate", "CritiqueArtifact")
        turn_id = str(getattr(response, "protocol_turn_id", ""))
        try:
            record = CritiqueRecord.from_model_payload(
                parsed.result_payload,
                critique_id=f"critique-{turn_id or ordinal}",
                source_turn_id=turn_id,
                candidates=candidates,
                obligations=obligations,
                peer_reviews=peer_reviews,
            )
            lineage = self._complete(response, budget)
        except Exception as error:
            self._fail(response, budget, "critique_payload_invalid")
            raise ModelResponseError("critique_payload_invalid") from error
        return CrossExamOutcome(
            replace(
                record,
                artifact_id=lineage.get("output_artifact_id", ""),
                message_id=lineage.get("message_id", ""),
                thread_id=lineage.get("thread_id", ""),
            ),
            turn_id,
        )

    def final_audit(
        self,
        *,
        problem: ProblemIR,
        candidate: CandidateSolution,
        obligations: list[ProofObligation],
        evidence: list[EvidenceRecord],
        critiques: list[CritiqueRecord],
        peer_reviews: list[PeerReviewRecord],
        rebuttals: list[RebuttalRecord],
        repair_lineage: list[dict],
        input_artifact_ids: tuple[str, ...],
        budget: CallBudget,
        max_tokens: int,
        ordinal: int = 1,
    ) -> FinalAuditOutcome:
        valid_finding_ids = {
            item.finding_id
            for critique in critiques
            for item in critique.findings
            if item.candidate_id == candidate.candidate_id
        }
        valid_obligation_ids = {item.obligation_id for item in obligations}
        allowed_artifact_ids = {item for item in input_artifact_ids if item}
        candidate_peer_finding_ids = {
            finding.finding_id
            for review in peer_reviews
            if review.candidate_id == candidate.candidate_id
            for finding in review.finding_items
        }
        candidate_critiques = []
        for critique in critiques:
            normalized = critique.to_dict()
            normalized["findings"] = [
                item
                for item in normalized["findings"]
                if item["candidate_id"] == candidate.candidate_id
            ]
            normalized["peer_review_assessments"] = [
                item
                for item in normalized["peer_review_assessments"]
                if item["finding_id"] in candidate_peer_finding_ids
                or item["finding_id"].split(":", 1)[-1]
                in candidate_peer_finding_ids
            ]
            if normalized["findings"] or normalized["peer_review_assessments"]:
                candidate_critiques.append(normalized)
        candidate_repair_lineage = [
            item
            for item in repair_lineage
            if candidate.candidate_id
            in {
                str(item.get("source_candidate_id", "")),
                str(item.get("proposed_candidate_id", "")),
            }
        ]
        payload = {
            "problem": problem.normalized_problem,
            "response_mode": problem.response_mode,
            "final_active_candidate": _public_candidate(candidate),
            "obligations": [item.to_dict() for item in obligations],
            "evidence": [
                item.to_dict()
                for item in evidence
                if item.candidate_id == candidate.candidate_id
                and item.transaction_status == "active"
            ],
            "critiques": candidate_critiques,
            "peer_reviews": [
                item.to_dict() for item in peer_reviews if item.candidate_id == candidate.candidate_id
            ],
            "rebuttals": [
                item.to_dict() for item in rebuttals if item.candidate_id == candidate.candidate_id
            ],
            "repair_lineage": candidate_repair_lineage,
            "allowed_reviewed_artifact_ids": sorted(allowed_artifact_ids),
        }
        compilation = self._compiler.compile_verifier_closure(
            user_content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            mode="final_audit",
        )
        response = self._call(
            compilation.messages,
            budget=budget,
            max_tokens=min(max_tokens or compilation.max_output_tokens, compilation.max_output_tokens),
            mode="final-audit",
            ordinal=ordinal,
            action_category="final_audit",
            input_artifact_ids=input_artifact_ids,
        )
        parsed = self._parse(response, "complete", "AuditArtifact")
        turn_id = str(getattr(response, "protocol_turn_id", ""))
        try:
            record = AuditRecord.from_model_payload(
                parsed.result_payload,
                audit_id=f"audit-{turn_id or ordinal}",
                source_turn_id=turn_id,
                candidate=candidate,
                valid_finding_ids=valid_finding_ids,
                valid_obligation_ids=valid_obligation_ids,
                allowed_artifact_ids=allowed_artifact_ids,
            )
            lineage = self._complete(response, budget)
        except Exception as error:
            self._fail(response, budget, "audit_payload_invalid")
            raise ModelResponseError("audit_payload_invalid") from error
        return FinalAuditOutcome(
            replace(
                record,
                artifact_id=lineage.get("output_artifact_id", ""),
                message_id=lineage.get("message_id", ""),
                thread_id=lineage.get("thread_id", ""),
            ),
            turn_id,
        )

    def _call(
        self,
        messages: list[dict[str, str]],
        *,
        budget: CallBudget,
        max_tokens: int,
        mode: str,
        ordinal: int,
        action_category: str,
        input_artifact_ids: tuple[str, ...],
    ) -> str:
        budget.consume(stage="verifier", optional=False, action_category=action_category)
        budget.record_prompt_chars(sum(len(item["content"]) for item in messages))
        return self._provider.chat(
            messages=messages,
            temperature=0.0,
            max_tokens=max_tokens,
            budget=budget,
            stage="verifier",
            turn_kind="verifier",
            agent_id=f"VerifierSkeptic:{mode}-{ordinal}",
            agent_action_protocol=True,
            input_artifact_ids=input_artifact_ids,
        )

    @staticmethod
    def _parse(response: str, action: str, artifact_type: str):
        try:
            parsed = AgentTurnPayloadParser().parse(response, allowed_actions=(action,))
        except (TypeError, ValueError) as error:
            raise ModelResponseError("verification_turn_payload_invalid") from error
        if parsed.payload.task_result_type != artifact_type:
            raise ModelResponseError("verification_turn_result_type_invalid")
        return parsed.payload

    @staticmethod
    def _complete(response: str, budget: CallBudget) -> dict[str, str]:
        runtime = budget.agent_runtime
        turn_id = str(getattr(response, "protocol_turn_id", ""))
        if runtime is None or not turn_id:
            return {}
        lineage = runtime.complete_model_turn(
            turn_id,
            str(response),
            agent_action_protocol=True,
        )
        call_index = getattr(response, "model_call_index", None)
        if call_index is not None:
            budget.record_model_call_lineage(call_index, lineage)
        return lineage

    @staticmethod
    def _fail(response: str, budget: CallBudget, failure_code: str) -> None:
        runtime = budget.agent_runtime
        turn_id = str(getattr(response, "protocol_turn_id", ""))
        if runtime is not None and turn_id:
            runtime.fail_model_turn(turn_id, failure_code)


def _public_candidate(candidate: CandidateSolution) -> dict:
    return {
        "candidate_id": candidate.candidate_id,
        "version": candidate.version,
        "role": candidate.role,
        "method": candidate.method,
        "final_answer": candidate.final_answer,
        "claims": [item.to_dict() for item in candidate.claims],
        "method_steps": [item.to_dict() for item in candidate.method_steps],
        "public_solution_steps": list(candidate.public_solution_steps),
        "assumptions": list(candidate.assumptions),
        "theorems": list(candidate.theorems),
        "unresolved_obligations": list(candidate.unresolved_obligations),
    }


def _public_peer_reviews(peer_reviews: list[PeerReviewRecord]) -> list[dict]:
    counts: dict[str, int] = {}
    for review in peer_reviews:
        for finding in review.finding_items:
            counts[finding.finding_id] = counts.get(finding.finding_id, 0) + 1
    payloads = []
    for review in peer_reviews:
        payload = review.to_dict()
        payload["finding_items"] = [
            {
                **finding,
                "finding_ref": (
                    finding["finding_id"]
                    if counts[finding["finding_id"]] == 1
                    else f"{review.review_id}:{finding['finding_id']}"
                ),
            }
            for finding in payload["finding_items"]
        ]
        payloads.append(payload)
    return payloads
