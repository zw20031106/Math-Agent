from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from mathforge.agents.prompt_compiler import PromptCompiler
from mathforge.agents.registry import PromptContractLoader
from mathforge.context.snapshots import RoleContextView
from mathforge.context.errors import ContextBudgetExceeded
from mathforge.harness.budget import CallBudget
from mathforge.harness.errors import BudgetExceeded, ModelTransportError
from mathforge.harness.provider import OfficialClientProvider
from mathforge.harness.problem_conditions import build_problem_condition_envelope
from mathforge.harness.schemas import (
    CandidateSolution,
    EvidenceRecord,
    LemmaCard,
    ProblemIR,
    ProofObligation,
)
from mathforge.verification.capabilities import (
    ClaimVerificationState,
    capability_verifies_claim,
)
from mathforge.verification.cross_review import (
    CandidateConflictMatrix,
    CandidateReviewSummary,
    candidate_review_segments,
    reviewable_obligation_ids,
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
    missing_condition: str = ""
    counterexample_summary: str = ""
    review_level: str = "obligation"
    review_target_ids: tuple[str, ...] = ()


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
        self._compiler = PromptCompiler(self._contracts)

    def review(
        self,
        problem: ProblemIR,
        candidates: list[CandidateSolution],
        obligations: dict[str, list[ProofObligation]],
        budget: CallBudget,
        *,
        max_tokens: int,
        context_view: RoleContextView | None = None,
        evidence: list[EvidenceRecord] | None = None,
        skill_context: str = "",
        peer_reviews: list[Any] | None = None,
        rebuttals: list[Any] | None = None,
    ) -> BatchVerificationResult:
        payload = self._review_payload(
            problem,
            candidates,
            obligations,
            evidence or [],
            peer_reviews or [],
            rebuttals or [],
        )
        if (
            not payload["reviewable_obligation_ids"]
            and not payload["review_targets"]
        ):
            return BatchVerificationResult(
                [],
                False,
                "no_reviewable_targets",
            )
        try:
            budget.consume(
                stage="verifier",
                stage_timeout_seconds=budget.stage_timeout_seconds("verifier"),
            )
            visible = (
                self._review_payload_from_view(context_view)
                if context_view is not None
                else payload
            )
            visible["candidate_conflict_matrix"] = payload[
                "candidate_conflict_matrix"
            ]
            visible["review_targets"] = payload["review_targets"]
            visible["reviewable_obligation_ids"] = payload[
                "reviewable_obligation_ids"
            ]
            visible["unreviewable_obligation_ids"] = payload[
                "unreviewable_obligation_ids"
            ]
            visible["response_mode"] = problem.response_mode
            visible["answer_type"] = problem.answer_type
            visible_payload = json.dumps(
                visible,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            user = (
                "Review this structured public batch using the supplied Claim-linked "
                "public solution segments. Return exactly one JSON object with findings "
                "that contain candidate_id, claim_id, obligation_ids, review_target_ids, "
                "review_level, status, public_rationale, missing_condition, and "
                "counterexample_summary.\n\n"
                f"Batch:\n{visible_payload}"
                + (
                    f"\n\nAuthorized skill guidance:\n{skill_context}"
                    if skill_context.strip()
                    else ""
                )
            )
            compilation = self._compiler.compile_role(
                "verifier_skeptic",
                user_content=user,
                runtime_instructions=(
                    "Challenge the supplied claims and required proof obligations. "
                    "Return JSON only. An obligation pass must name both a real claim_id "
                    "and supported obligation_ids. An answer-level or claim-level pass "
                    "must name a real claim_id and supplied review_target_ids. "
                    "Classify every supplied conflict target for both candidates. "
                    "Unknown is not pass. "
                    "For proof_full, treat an omitted essential proof step or theorem "
                    "hypothesis as fail or unknown, never pass. Write formulas in "
                    "public fields using $...$ LaTeX delimiters. "
                    "Do not emit native tool calls or private reasoning."
                ),
            )
            messages = compilation.messages
            budget.record_prompt_chars(
                sum(len(message["content"]) for message in messages),
                components=compilation.prompt_component_tokens,
            )
            response = self._provider.chat(
                messages=messages,
                temperature=0.0,
                max_tokens=PromptCompiler.bounded_output_tokens(
                    max_tokens,
                    compilation.max_output_tokens,
                ),
                budget=budget,
                stage="verifier",
                turn_kind="verifier",
                agent_id="VerifierSkeptic",
            )
            if budget.deadline.must_finalize():
                return BatchVerificationResult([], False, "finalize_cutoff")
        except (BudgetExceeded, ModelTransportError, ContextBudgetExceeded):
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
        evidence: list[EvidenceRecord],
        peer_reviews: list[Any] | None = None,
        rebuttals: list[Any] | None = None,
    ) -> dict:
        condition_envelope = build_problem_condition_envelope(problem)
        summaries = [
            CandidateReviewSummary.from_candidate(candidate)
            for candidate in candidates
        ]
        matrix = CandidateConflictMatrix.build(summaries, peer_reviews or [])
        reviewable_ids = reviewable_obligation_ids(
            candidates,
            obligations,
        )
        if not reviewable_ids:
            # A Candidate with claims but no real obligation edge still needs
            # an observable Verifier phase: transport/protocol health must be
            # distinguishable from a structural unmapped-obligation result.
            # The model cannot turn this into evidence because the parser
            # rejects non-Claim diagnostic references.
            reviewable_ids = tuple(
                obligation.obligation_id
                for candidate in candidates
                if candidate.claims
                for obligation in obligations.get(candidate.candidate_id, [])
                if obligation.required
            )
        all_required_ids = {
            obligation.obligation_id
            for candidate in candidates
            for obligation in obligations.get(candidate.candidate_id, [])
            if obligation.required
        }
        return {
            "problem": problem.normalized_problem,
            "problem_condition_envelope": condition_envelope.to_dict(),
            "response_mode": problem.response_mode,
            "answer_type": problem.answer_type,
            "conditions": list(problem.assumptions),
            "candidate_review_summaries": [
                summary.to_dict() for summary in summaries
            ],
            "candidate_conflict_matrix": matrix.to_dict(),
            "review_targets": [
                target.to_dict()
                for target in matrix.review_targets()
            ],
            "solver_peer_reviews": [
                item.to_dict() if hasattr(item, "to_dict") else dict(item)
                for item in (peer_reviews or [])
            ],
            "solver_rebuttals": [
                item.to_dict() if hasattr(item, "to_dict") else dict(item)
                for item in (rebuttals or [])
            ],
            "reviewable_obligation_ids": list(reviewable_ids),
            "unreviewable_obligation_ids": sorted(
                all_required_ids - set(reviewable_ids)
            ),
            "candidates": [
                {
                    "candidate_id": candidate.candidate_id,
                    "method": candidate.method,
                    "final_answer": candidate.final_answer,
                    "assumptions": list(candidate.assumptions),
                    "theorems": list(candidate.theorems),
                    "claims": [claim.to_dict() for claim in candidate.claims],
                    "method_steps": [
                        method_step.to_dict()
                        for method_step in candidate.method_steps
                    ],
                    "public_solution_steps": list(
                        candidate.public_solution_steps
                    ),
                    "review_segments": candidate_review_segments(
                        candidate
                    ),
                    "evidence": [
                        record.to_dict()
                        for record in evidence
                        if record.candidate_id == candidate.candidate_id
                    ],
                    "obligations": [
                        obligation.to_dict()
                        for obligation in obligations.get(candidate.candidate_id, [])
                        if obligation.obligation_id in reviewable_ids
                    ],
                }
                for candidate in candidates
            ],
        }

    @staticmethod
    def _review_payload_from_view(context_view: RoleContextView) -> dict:
        payload = context_view.payload
        obligations = payload.get("obligations", [])
        evidence = payload.get("evidence", [])
        return {
            "problem": payload.get("original_problem", ""),
            "problem_condition_envelope": payload.get(
                "metadata", {}
            ).get("problem_condition_envelope", {}),
            "candidates": [
                (
                    {
                    key: candidate[key]
                    for key in (
                        "candidate_id",
                        "method",
                        "final_answer",
                        "assumptions",
                        "theorems",
                        "claims",
                        "method_steps",
                        "public_solution_steps",
                        "review_segments",
                        "unresolved_obligations",
                    )
                    if key in candidate
                    }
                    | {
                    "evidence": [
                        record
                        for record in evidence
                        if record.get("candidate_id")
                        == candidate.get("candidate_id")
                    ],
                    "obligations": [
                        obligation
                        for obligation in obligations
                        if str(obligation.get("obligation_id", "")).startswith(
                            f"{candidate.get('candidate_id')}:"
                        )
                        and set(obligation.get("source_claim_ids", []))
                        .intersection(
                            {
                                str(claim.get("claim_id", ""))
                                for claim in candidate.get("claims", [])
                                if isinstance(claim, dict)
                            }
                        )
                    ],
                    }
                )
                for candidate in payload.get("candidates", [])
            ],
            "conditions": payload.get("conditions", []),
            "metadata": payload.get("metadata", {}),
            "context_snapshot_id": context_view.snapshot_id,
        }

    @staticmethod
    def _parse_findings(
        response: str,
        candidates: list[CandidateSolution],
        obligations: dict[str, list[ProofObligation]],
    ) -> list[SkepticFinding]:
        payload = _json_payload(response)
        # The prompt requests ``{"findings": [...]}``, but the official
        # Intern endpoint can occasionally unwrap that single field and
        # return the findings array itself. Treat that response as the same
        # public artifact; all candidate/claim/obligation validation below
        # still applies and no Host-owned identifiers are synthesized.
        if isinstance(payload, dict):
            raw_findings = payload.get("findings", [])
        elif isinstance(payload, list):
            raw_findings = payload
        else:
            raw_findings = []
        if not isinstance(raw_findings, list):
            return []
        candidate_by_id = {candidate.candidate_id: candidate for candidate in candidates}
        review_targets = {
            target.target_id: target
            for target in CandidateConflictMatrix.build(
                [
                    CandidateReviewSummary.from_candidate(candidate)
                    for candidate in candidates
                ]
            ).review_targets()
        }
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
            raw_target_ids = item.get("review_target_ids", [])
            if isinstance(raw_target_ids, str):
                raw_target_ids = [raw_target_ids]
            if not isinstance(raw_target_ids, list):
                raw_target_ids = []
            review_target_ids = tuple(
                sorted(
                    {
                        str(value)
                        for value in raw_target_ids
                        if str(value) in review_targets
                        and candidate_id
                        in review_targets[str(value)].candidate_ids
                    }
                )
            )
            review_level = str(
                item.get(
                    "review_level",
                    (
                        review_targets[review_target_ids[0]].level
                        if review_target_ids
                        else "obligation"
                    ),
                )
            ).strip().lower()
            if review_level not in {"obligation", "answer", "claim"}:
                review_level = "obligation"
            if review_target_ids:
                target_levels = {
                    review_targets[target_id].level
                    for target_id in review_target_ids
                }
                if len(target_levels) != 1:
                    continue
                review_level = next(iter(target_levels))
            if status == "pass":
                obligation_ids = [
                    obligation_id
                    for obligation_id in obligation_ids
                    if claim_id is not None
                    and claim_id in own_obligations[obligation_id].source_claim_ids
                ]
                if (
                    claim_id is None
                    or (
                        not obligation_ids
                        and not review_target_ids
                    )
                ):
                    continue
            key = (
                candidate_id,
                claim_id,
                tuple(obligation_ids),
                review_target_ids,
                review_level,
                status,
            )
            if key in seen:
                continue
            seen.add(key)
            results.append(
                SkepticFinding(
                    candidate_id,
                    claim_id,
                    obligation_ids,
                    status,
                    str(
                        item.get(
                            "public_rationale",
                            item.get("description", "VerifierSkeptic finding"),
                        )
                    )[:1000],
                    str(item.get("missing_condition", "")),
                    str(item.get("counterexample_summary", "")),
                    review_level,
                    review_target_ids,
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
                and capability_verifies_claim(record.capability)
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
        candidate_id = lemma.source_candidate_id
        claim_id = lemma.source_claim_id
        matching = [
            record
            for record in evidence
            if record.candidate_id == candidate_id and record.claim_id == claim_id
            and record.transaction_status == "active"
        ]
        if any(
            record.status == "fail"
            and record.strength == "hard"
            and capability_verifies_claim(record.capability)
            for record in matching
        ):
            lemma.status = "rejected"
        elif any(
            record.status == "pass"
            and capability_verifies_claim(record.capability)
            for record in matching
        ):
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
            if (
                claim is not None
                and claim.verification_state
                == ClaimVerificationState.SEMANTICALLY_VERIFIED.value
            ):
                lemma.status = "verified"
            elif (
                claim is not None
                and claim.verification_state == ClaimVerificationState.REJECTED.value
            ):
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
