from __future__ import annotations

import json

from mathforge.harness.budget import CallBudget
from mathforge.harness.provider import OfficialClientProvider
from mathforge.harness.schemas import CandidateSolution, EvidenceRecord, ProblemIR
from mathforge.parsing.solution_parser import SolutionParser


class RepairAgent:
    def __init__(self, provider: OfficialClientProvider, parser: SolutionParser) -> None:
        self._provider = provider
        self._parser = parser

    def repair(
        self,
        problem: ProblemIR,
        candidate: CandidateSolution,
        affected_claim_ids: list[str],
        evidence: list[EvidenceRecord],
        budget: CallBudget,
        *,
        max_tokens: int,
    ) -> CandidateSolution:
        local_claims = [
            claim.to_dict() for claim in candidate.claims if claim.claim_id in affected_claim_ids
        ]
        local_evidence = [
            record.to_dict()
            for record in evidence
            if record.candidate_id == candidate.candidate_id
            and record.claim_id in affected_claim_ids
        ]
        budget.consume()
        response = self._provider.chat(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are RepairAgent. Repair only the supplied failed claim dependency "
                        "closure. Return CandidateSolution JSON with replacement claims."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Problem:\n{problem.normalized_problem}\n\n"
                        f"Affected claims:\n{json.dumps(local_claims, ensure_ascii=False)}\n"
                        f"Evidence:\n{json.dumps(local_evidence, ensure_ascii=False)}"
                    ),
                },
            ],
            temperature=0.1,
            max_tokens=max_tokens,
        )
        return self._parser.parse(
            response,
            candidate_id=f"{candidate.candidate_id}-v{candidate.version + 1}",
            role="RepairAgent",
            answer_type=candidate.answer_type,
        )
