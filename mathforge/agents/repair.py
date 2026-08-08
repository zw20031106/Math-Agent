from __future__ import annotations

import json

from mathforge.agents.prompt_compiler import PromptCompiler
from mathforge.agents.registry import PromptContractLoader
from mathforge.context.snapshots import RoleContextView
from mathforge.harness.budget import CallBudget
from mathforge.harness.errors import ModelResponseError
from mathforge.harness.model_candidate_contract import (
    MODEL_CANDIDATE_HOST_FIELDS,
    MODEL_CANDIDATE_PATCH_FIELDS,
)
from mathforge.harness.provider import OfficialClientProvider
from mathforge.harness.schemas import (
    CandidatePatch,
    CandidateSolution,
    EvidenceRecord,
    ProblemIR,
)
from mathforge.parsing.solution_parser import SolutionParser


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
        critique: dict | None = None,
        critique_artifact_id: str = "",
    ) -> CandidatePatch:
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
            + (
                "\n\nAuthorized CritiqueArtifact:\n"
                + json.dumps(critique, ensure_ascii=False, separators=(",", ":"))
                if critique
                else ""
            )
        )
        compilation = self._compiler.compile_role(
            "repair",
            user_content=user,
            runtime_instructions=(
                "Repair only the supplied failed claim impact closure. "
                "Return only replacement_claims, corrected local public steps, "
                "the corrected or unchanged exact final answer, and unresolved "
                "obligations. Do not rewrite unrelated content or emit native "
                f"tool calls. Host response mode is {problem.response_mode}."
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
            turn_kind="repair",
            agent_id=f"RepairAgent:{candidate.candidate_id}",
            input_artifact_ids=(
                (critique_artifact_id,)
                if critique_artifact_id
                else ()
            ),
        )
        if budget.deadline.must_finalize():
            raise RuntimeError("repair response arrived after finalize cutoff")
        budget.ensure_stage("solution_parser")
        patch = self._parse_patch(
            response,
            candidate,
            affected_claim_ids,
        )
        budget.record_model_response_validation(
            getattr(response, "model_call_index", None),
            (
                "strict_repair_patch"
                if patch.parse_status == "strict_json"
                and not patch.contract_deviations
                else "recovered_repair_patch"
            ),
            rejected=False,
        )
        return patch

    def _parse_patch(
        self,
        response: str,
        candidate: CandidateSolution,
        affected_claim_ids: list[str],
    ) -> CandidatePatch:
        payload, parse_status = self._parser._payload(response.strip())
        if payload is None:
            raise ModelResponseError("repair_patch_invalid")
        deviations: list[str] = []
        raw_replacements = payload.get("replacement_claims")
        if raw_replacements is None and "claims" in payload:
            raw_replacements = payload["claims"]
            deviations.append("claims:legacy_patch_alias")
        normalized_patch_fields = set(payload)
        if "claims" in normalized_patch_fields:
            normalized_patch_fields.add("replacement_claims")
            normalized_patch_fields.remove("claims")
        deviations.extend(
            f"{name}:missing"
            for name in sorted(
                MODEL_CANDIDATE_PATCH_FIELDS - normalized_patch_fields
            )
        )
        deviations.extend(
            f"{name}:host_owned"
            for name in sorted(
                MODEL_CANDIDATE_HOST_FIELDS.intersection(payload)
            )
        )
        deviations.extend(
            f"{name}:ignored"
            for name in sorted(
                normalized_patch_fields
                - MODEL_CANDIDATE_PATCH_FIELDS
                - MODEL_CANDIDATE_HOST_FIELDS
            )
        )
        if not isinstance(raw_replacements, list):
            raise ModelResponseError("repair_patch_invalid")

        normalized, alias_deviations = self._parser._normalize_aliases(
            {"claims": raw_replacements}
        )
        deviations.extend(alias_deviations)
        normalized_replacements = normalized["claims"]
        replacement_ids = {
            str(item.get("claim_id", ""))
            for item in normalized_replacements
            if isinstance(item, dict)
        }
        original_claims = {
            claim.claim_id: {
                "claim_id": claim.claim_id,
                "statement": claim.statement,
                "depends_on": list(claim.depends_on),
                "check_type": claim.check_type,
                "importance": claim.importance,
            }
            for claim in candidate.claims
        }
        for item in normalized_replacements:
            if isinstance(item, dict):
                original_claims[str(item.get("claim_id", ""))] = item
        synthetic_payload = {
            "method": candidate.method,
            "method_steps": [
                {
                    "step_id": step.step_id,
                    "kind": step.kind,
                    "claim_ids": list(step.claim_ids),
                    "theorem": step.theorem,
                }
                for step in candidate.method_steps
            ],
            "solution_text": "\n".join(
                item
                for item in payload.get("public_solution_steps", [])
                if isinstance(item, str)
            ),
            "public_solution_steps": [
                item
                for item in payload.get("public_solution_steps", [])
                if isinstance(item, str)
            ],
            "final_answer": (
                payload.get("final_answer", "")
                if isinstance(payload.get("final_answer", ""), str)
                else ""
            ),
            "assumptions": list(candidate.assumptions),
            "theorems": list(candidate.theorems),
            "claims": list(original_claims.values()),
            "unresolved_obligations": [
                item
                for item in payload.get("unresolved_obligations", [])
                if isinstance(item, str)
            ],
        }
        normalized_candidate = self._parser.parse(
            json.dumps(synthetic_payload, ensure_ascii=False),
            candidate_id=f"{candidate.candidate_id}-patch",
            role="RepairAgent",
            answer_type=candidate.answer_type,
        )
        patch = CandidatePatch(
            source_candidate_id=candidate.candidate_id,
            base_version=candidate.version,
            affected_claim_ids=list(affected_claim_ids),
            replacement_claims=[
                claim
                for claim in normalized_candidate.claims
                if claim.claim_id in replacement_ids
            ],
            final_answer=synthetic_payload["final_answer"],
            public_solution_steps=synthetic_payload["public_solution_steps"],
            unresolved_obligations=synthetic_payload[
                "unresolved_obligations"
            ],
            parse_status=parse_status,
            contract_deviations=deviations,
        )
        patch.validate()
        return patch
