from __future__ import annotations

import json

from mathforge.agents.prompt_compiler import PromptCompiler
from mathforge.agents.registry import PromptContractLoader
from mathforge.context.snapshots import RoleContextView
from mathforge.harness.budget import CallBudget
from mathforge.harness.errors import ModelResponseError
from mathforge.harness.provider import OfficialClientProvider
from mathforge.harness.schemas import CandidateSolution, EvidenceRecord, ProblemIR
from mathforge.parsing.solution_parser import (
    SolutionParser,
    candidate_response_validation,
)


class RepairAgent:
    def __init__(
        self,
        provider: OfficialClientProvider,
        parser: SolutionParser,
        contracts: PromptContractLoader | None = None,
    ) -> None:
        self._provider = provider
        self._parser = parser
        self._contracts = contracts or PromptContractLoader()
        self._compiler = PromptCompiler(self._contracts)

    def repair(
        self,
        problem: ProblemIR,
        candidate: CandidateSolution,
        affected_claim_ids: list[str],
        evidence: list[EvidenceRecord],
        budget: CallBudget,
        *,
        max_tokens: int,
        context_view: RoleContextView | None = None,
        skill_context: str = "",
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
        budget.consume(stage="repair")
        user = (
            f"Problem:\n{problem.normalized_problem}\n\n"
            + (
                f"Authorized repair context:\n{context_view.to_prompt_json()}"
                if context_view is not None
                else (
                    f"Affected claims:\n{json.dumps(local_claims, ensure_ascii=False)}\n"
                    f"Evidence:\n{json.dumps(local_evidence, ensure_ascii=False)}"
                )
            )
            + (
                f"\n\nAuthorized skill guidance:\n{skill_context}"
                if skill_context.strip()
                else ""
            )
        )
        compilation = self._compiler.compile_role(
            "repair",
            user_content=user,
            runtime_instructions=(
                "Repair only the supplied failed claim impact closure. "
                "Return exactly one CandidateSolution model-fields JSON object with "
                "replacement claims, corrected public steps, the corrected or unchanged "
                "exact final answer, and unresolved obligations. Do not rewrite unrelated "
                "content or emit native tool calls."
            ),
        )
        messages = compilation.messages
        budget.record_prompt_chars(
            sum(len(message["content"]) for message in messages)
        )
        response = self._provider.chat(
            messages=messages,
            temperature=0.1,
            max_tokens=PromptCompiler.bounded_output_tokens(
                max_tokens,
                compilation.max_output_tokens,
            ),
            budget=budget,
            stage="repair",
        )
        if budget.deadline.must_finalize():
            raise RuntimeError("repair response arrived after finalize cutoff")
        budget.ensure_stage("solution_parser")
        repaired = self._parser.parse(
            response,
            candidate_id=f"{candidate.candidate_id}-v{candidate.version + 1}",
            role="RepairAgent",
            answer_type=candidate.answer_type,
        )
        validation_code, rejected = candidate_response_validation(repaired)
        budget.record_model_response_validation(
            getattr(response, "model_call_index", None),
            validation_code,
            rejected=rejected,
        )
        if rejected:
            raise ModelResponseError(validation_code)
        return repaired
