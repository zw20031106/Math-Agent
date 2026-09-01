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
from mathforge.harness.problem_conditions import build_problem_condition_envelope
from mathforge.harness.schemas import (
    CandidatePatch,
    CandidateSolution,
    Claim,
    EvidenceRecord,
    ProblemIR,
)
from mathforge.parsing.solution_parser import SolutionParser
from mathforge.verification.capabilities import derive_claim_kind


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
        condition_envelope = build_problem_condition_envelope(problem)
        local_claims = [
            claim.to_dict() for claim in candidate.claims if claim.claim_id in affected_claim_ids
        ]
        local_evidence = [
            record.to_dict()
            for record in evidence
            if record.candidate_id == candidate.candidate_id
            and record.claim_id in affected_claim_ids
        ]
        budget.consume(
            stage="repair",
            stage_timeout_seconds=budget.stage_timeout_seconds("repair"),
        )
        user = (
            f"Problem:\n{problem.normalized_problem}\n\n"
            f"{condition_envelope.to_prompt()}\n\n"
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
            sum(len(message["content"]) for message in messages),
            components=compilation.prompt_component_tokens,
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
        valid_claim_ids = {claim.claim_id for claim in candidate.claims}
        affected = set(affected_claim_ids)
        replacement_claims: list[Claim] = []
        allowed_claim_fields = {
            "claim_id",
            "statement",
            "depends_on",
            "check_type",
            "importance",
        }
        for index, item in enumerate(normalized_replacements):
            if not isinstance(item, dict):
                raise ModelResponseError("repair_patch_invalid")
            deviations.extend(
                f"replacement_claims[{index}].{name}:ignored"
                for name in sorted(set(item) - allowed_claim_fields)
            )
            claim_id = str(item.get("claim_id", "")).strip()
            statement = str(item.get("statement", "")).strip()
            dependencies = item.get("depends_on", [])
            check_type = str(item.get("check_type", "reasoning")).strip()
            importance = str(item.get("importance", "supporting")).strip()
            if (
                claim_id not in affected
                or claim_id not in valid_claim_ids
                or not statement
                or not isinstance(dependencies, list)
                or any(not isinstance(value, str) for value in dependencies)
                or bool(set(dependencies) - valid_claim_ids)
                or importance not in {"critical", "supporting"}
            ):
                raise ModelResponseError("repair_patch_invalid")
            replacement = Claim(
                claim_id=claim_id,
                statement=statement,
                depends_on=list(dependencies),
                check_type=check_type or "reasoning",
                importance=importance,
                claim_kind=derive_claim_kind(check_type or "reasoning"),
            )
            replacement.validate()
            replacement_claims.append(replacement)
        final_answer = (
            payload.get("final_answer", "")
            if isinstance(payload.get("final_answer", ""), str)
            else ""
        )
        public_solution_steps = [
            item
            for item in payload.get("public_solution_steps", [])
            if isinstance(item, str)
        ]
        unresolved_obligations = [
            item
            for item in payload.get("unresolved_obligations", [])
            if isinstance(item, str)
        ]
        patch = CandidatePatch(
            source_candidate_id=candidate.candidate_id,
            base_version=candidate.version,
            affected_claim_ids=list(affected_claim_ids),
            replacement_claims=replacement_claims,
            final_answer=final_answer,
            public_solution_steps=public_solution_steps,
            unresolved_obligations=unresolved_obligations,
            parse_status=parse_status,
            contract_deviations=deviations,
        )
        patch.validate()
        return patch
