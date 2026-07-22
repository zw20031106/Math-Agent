from __future__ import annotations

from dataclasses import dataclass
import json
import re

from mathforge.agents.registry import PromptContractLoader
from mathforge.harness.budget import CallBudget
from mathforge.harness.provider import OfficialClientProvider
from mathforge.harness.schemas import (
    CandidateSolution,
    EvidenceRecord,
    LemmaCard,
    ProblemIR,
    ProofObligation,
)


@dataclass(frozen=True)
class VerificationFinding:
    candidate_id: str
    status: str
    failed_claim_ids: list[str]
    unresolved_obligation_ids: list[str]


@dataclass(frozen=True)
class SkepticFinding:
    candidate_id: str
    claim_id: str | None
    obligation_ids: list[str]
    status: str
    description: str


@dataclass(frozen=True)
class BatchVerificationResult:
    findings: list[SkepticFinding]
    used_llm: bool
    reason: str


class VerifierSkepticAgent:
    """Review all candidates in one budgeted call and emit soft findings only."""

    def __init__(
        self,
        provider: OfficialClientProvider,
        contracts: PromptContractLoader | None = None,
    ) -> None:
        self._provider = provider
        self._contracts = contracts or PromptContractLoader()

    def review(
        self,
        problem: ProblemIR,
        candidates: list[CandidateSolution],
        obligations: dict[str, list[ProofObligation]],
        budget: CallBudget,
        *,
        max_tokens: int,
    ) -> BatchVerificationResult:
        payload = self._review_payload(problem, candidates, obligations)
        try:
            budget.consume()
            response = self._provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": self._contracts.system_prompt(
                            "verifier_skeptic",
                            (
                                "Challenge the supplied claims and required proof obligations. "
                                "Return JSON only. A pass must name both a real claim_id and one "
                                "or more obligation_ids supported by that claim. Unknown is not pass."
                            ),
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "Review this structured batch. Do not reconstruct or rewrite the full "
                            "solutions. Return {\"findings\":[{\"candidate_id\":\"...\","
                            "\"claim_id\":\"...\",\"obligation_ids\":[\"...\"],"
                            "\"status\":\"pass|fail|unknown\",\"description\":\"...\"}]}.\n\n"
                            f"Batch:\n{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
                        ),
                    },
                ],
                temperature=0.0,
                max_tokens=max_tokens,
            )
            budget.record_tokens(max(1, len(response) // 4))
        except Exception:
            return BatchVerificationResult([], False, "verifier_unavailable")
        findings = self._parse_findings(response, candidates, obligations)
        return BatchVerificationResult(
            findings,
            True,
            "accepted" if findings else "invalid_or_empty_findings",
        )

    @staticmethod
    def _review_payload(
        problem: ProblemIR,
        candidates: list[CandidateSolution],
        obligations: dict[str, list[ProofObligation]],
    ) -> dict:
        return {
            "problem": problem.normalized_problem,
            "problem_type": problem.problem_type,
            "assumptions": list(problem.assumptions),
            "candidates": [
                {
                    "candidate_id": candidate.candidate_id,
                    "method": candidate.method,
                    "final_answer": candidate.final_answer,
                    "assumptions": list(candidate.assumptions),
                    "theorems": list(candidate.theorems),
                    "claims": [claim.to_dict() for claim in candidate.claims],
                    "obligations": [
                        obligation.to_dict()
                        for obligation in obligations.get(candidate.candidate_id, [])
                    ],
                }
                for candidate in candidates
            ],
        }

    @staticmethod
    def _parse_findings(
        response: str,
        candidates: list[CandidateSolution],
        obligations: dict[str, list[ProofObligation]],
    ) -> list[SkepticFinding]:
        payload = _json_payload(response)
        raw_findings = payload.get("findings", []) if isinstance(payload, dict) else []
        if not isinstance(raw_findings, list):
            return []
        candidate_by_id = {candidate.candidate_id: candidate for candidate in candidates}
        results: list[SkepticFinding] = []
        seen: set[tuple] = set()
        for item in raw_findings[:128]:
            if not isinstance(item, dict):
                continue
            candidate_id = str(item.get("candidate_id", ""))
            candidate = candidate_by_id.get(candidate_id)
            status = str(item.get("status", "unknown")).lower()
            if candidate is None or status not in {"pass", "fail", "unknown"}:
                continue
            claim_id = str(item.get("claim_id", "")) or None
            valid_claim_ids = {claim.claim_id for claim in candidate.claims}
            if claim_id not in valid_claim_ids:
                claim_id = None
            raw_ids = item.get("obligation_ids", [])
            if isinstance(raw_ids, str):
                raw_ids = [raw_ids]
            if not isinstance(raw_ids, list):
                raw_ids = []
            own_obligations = {
                obligation.obligation_id: obligation
                for obligation in obligations.get(candidate_id, [])
            }
            obligation_ids = sorted(
                {str(value) for value in raw_ids if str(value) in own_obligations}
            )
            if status == "pass":
                obligation_ids = [
                    obligation_id
                    for obligation_id in obligation_ids
                    if claim_id is not None
                    and claim_id in own_obligations[obligation_id].source_claim_ids
                ]
                if claim_id is None or not obligation_ids:
                    continue
            key = (candidate_id, claim_id, tuple(obligation_ids), status)
            if key in seen:
                continue
            seen.add(key)
            results.append(
                SkepticFinding(
                    candidate_id,
                    claim_id,
                    obligation_ids,
                    status,
                    str(item.get("description", "VerifierSkeptic finding"))[:1000],
                )
            )
        return results


class VerifierSkeptic:
    """Build a conservative verdict from deterministic evidence and obligations."""

    def review(
        self,
        candidate: CandidateSolution,
        evidence: list[EvidenceRecord],
        obligations: list[ProofObligation],
    ) -> VerificationFinding:
        failed_claim_ids = sorted(
            {
                record.claim_id
                for record in evidence
                if record.candidate_id == candidate.candidate_id
                and record.claim_id is not None
                and record.status == "fail"
                and record.strength == "hard"
            }
        )
        unresolved = [
            obligation.obligation_id
            for obligation in obligations
            if obligation.required and obligation.status != "satisfied"
        ]
        if failed_claim_ids or any(item.status == "failed" for item in obligations):
            status = "failed"
        elif unresolved:
            status = "incomplete"
        else:
            status = "verified"
        return VerificationFinding(candidate.candidate_id, status, failed_claim_ids, unresolved)


class LemmaVerifier:
    def verify(
        self,
        lemma: LemmaCard,
        candidates: list[CandidateSolution],
        evidence: list[EvidenceRecord],
    ) -> LemmaCard:
        source = lemma.proof_sketch.removeprefix("Extracted from ")
        candidate_id, separator, claim_id = source.partition(":")
        matching = [
            record
            for record in evidence
            if record.candidate_id == candidate_id and record.claim_id == claim_id
        ]
        if any(record.status == "fail" and record.strength == "hard" for record in matching):
            lemma.status = "rejected"
        elif any(record.status == "pass" and record.strength == "hard" for record in matching):
            lemma.status = "verified"
        else:
            claim = next(
                (
                    claim
                    for candidate in candidates
                    if candidate.candidate_id == candidate_id
                    for claim in candidate.claims
                    if claim.claim_id == claim_id
                ),
                None,
            )
            if claim is not None and claim.status == "verified":
                lemma.status = "verified"
            elif claim is not None and claim.status == "rejected":
                lemma.status = "rejected"
            else:
                lemma.status = "conflicted"
        lemma.evidence_ids = [record.evidence_id for record in matching]
        return lemma


def _json_payload(response: str):
    text = str(response).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for match in re.finditer(r"[\[{]", text):
        try:
            value, _ = decoder.raw_decode(text[match.start() :])
            if isinstance(value, (dict, list)):
                return value
        except json.JSONDecodeError:
            continue
    return None
