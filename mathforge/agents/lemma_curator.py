from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re

from mathforge.agent_runtime.action_registry import ActionRegistry
from mathforge.agent_runtime.protocol import AgentTurnPayloadParser, ParsedAgentTurn
from mathforge.agents.prompt_compiler import PromptCompiler
from mathforge.agents.registry import PromptContractLoader
from mathforge.context.claim_graph import namespaced_claim_id
from mathforge.harness.budget import CallBudget
from mathforge.harness.errors import ModelResponseError
from mathforge.harness.provider import OfficialClientProvider
from mathforge.harness.problem_conditions import build_problem_condition_envelope
from mathforge.harness.schemas import (
    CandidateSolution,
    LemmaCard,
    ProofObligation,
)


_TOKEN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")
_ACTION_REGISTRY = ActionRegistry()


@dataclass(frozen=True)
class LLMLemmaRequest:
    problem: str
    plan_id: str
    plan_summary: str
    conditions: tuple[str, ...]
    target_obligation_ids: tuple[str, ...]
    request_text: str
    recipient_role: str
    source_round: int = 1
    condition_envelope: ProblemConditionEnvelope | None = None


@dataclass(frozen=True)
class LLMLemmaOutcome:
    parsed: ParsedAgentTurn
    lemmas: tuple[LemmaCard, ...]
    turn_id: str = ""


class LLMLemmaCuratorAgent:
    """Independent LLM LemmaCurator; deterministic curation remains fallback."""

    role = "LemmaCurator"

    def __init__(
        self,
        provider: OfficialClientProvider,
        contracts: PromptContractLoader | None = None,
    ) -> None:
        self._provider = provider
        self._compiler = PromptCompiler(contracts or PromptContractLoader())

    def execute(
        self,
        request: LLMLemmaRequest,
        budget: CallBudget,
        *,
        max_tokens: int,
        optional: bool = False,
    ) -> LLMLemmaOutcome:
        envelope = request.condition_envelope or build_problem_condition_envelope(
            request
        )
        user_content = json.dumps(
            {
                "problem": request.problem,
                "problem_condition_envelope": envelope.to_dict(),
                "plan_id": request.plan_id,
                "plan_summary": request.plan_summary,
                "conditions": list(request.conditions),
                "target_obligation_ids": list(request.target_obligation_ids),
                "lemma_request": request.request_text,
                "reply_recipient_role": request.recipient_role,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        compilation = self._compiler.compile_role(
            "lemma_curator",
            user_content=user_content,
            runtime_instructions=(
                "Set outbound_intents to exactly "
                f'[{json.dumps({"recipient_role": request.recipient_role}, ensure_ascii=False)}]. '
                "The Host validates the recipient."
            ),
        )
        budget.consume(
            stage="lemma",
            optional=optional,
            action_category="speculative_exploration",
        )
        budget.record_prompt_chars(
            sum(len(message["content"]) for message in compilation.messages),
            components=compilation.prompt_component_tokens,
        )
        response = self._provider.chat(
            messages=compilation.messages,
            temperature=0.0,
            max_tokens=PromptCompiler.bounded_output_tokens(
                max_tokens,
                compilation.max_output_tokens,
            ),
            budget=budget,
            stage="lemma",
            turn_kind="lemma_curator",
            agent_id="LemmaCurator",
            agent_action_protocol=True,
        )
        try:
            parsed = AgentTurnPayloadParser().parse(
                response,
                allowed_actions=_ACTION_REGISTRY.prompt_actions(
                    self.role,
                    phase="lemma_turn",
                ),
                truncated=bool(
                    getattr(response, "output_budget_exceeded", False)
                    or str(getattr(response, "finish_reason", "")).casefold()
                    == "length"
                ),
                truncation_reason=(
                    "finish_reason_length"
                    if str(getattr(response, "finish_reason", "")).casefold()
                    == "length"
                    else "observed_output_exceeded_contract"
                    if getattr(response, "output_budget_exceeded", False)
                    else ""
                ),
            )
            if parsed.payload.action == "abstain":
                if parsed.payload.task_result_type != "CheckpointArtifact":
                    raise ValueError("Lemma abstain result type is invalid")
                lemmas: tuple[LemmaCard, ...] = ()
            else:
                if parsed.payload.task_result_type != "LemmaArtifact":
                    raise ValueError("Lemma result type is invalid")
                if not parsed.payload.outbound_intents or str(
                    parsed.payload.outbound_intents[0].get(
                        "recipient_role",
                        "",
                    )
                ) != request.recipient_role:
                    raise ValueError("Lemma reply recipient is invalid")
                lemmas = (
                    ()
                    if parsed.partial
                    else self._parse_lemmas(parsed, request)
                )
        except (TypeError, ValueError) as error:
            self._fail_protocol(response, budget, "lemma_agent_payload_invalid")
            raise ModelResponseError("lemma_agent_payload_invalid") from error
        self._complete_protocol(response, budget)
        return LLMLemmaOutcome(
            parsed,
            lemmas,
            str(getattr(response, "protocol_turn_id", "")),
        )

    @staticmethod
    def _parse_lemmas(
        parsed: ParsedAgentTurn,
        request: LLMLemmaRequest,
    ) -> tuple[LemmaCard, ...]:
        result = parsed.payload.result_payload
        if not isinstance(result, dict) or set(result) != {"lemmas"}:
            raise ValueError("Lemma result_payload is invalid")
        raw_lemmas = result["lemmas"]
        if not isinstance(raw_lemmas, list):
            raise ValueError("lemmas must be a list")
        cards: list[LemmaCard] = []
        seen: set[str] = set()
        fields = {
            "statement",
            "conditions",
            "dependencies",
            "proof_sketch",
            "target_obligation_ids",
        }
        for index, item in enumerate(raw_lemmas, start=1):
            if not isinstance(item, dict) or set(item) != fields:
                raise ValueError("Lemma fields are invalid")
            statement = " ".join(str(item["statement"]).split())
            key = statement.casefold()
            if not statement or key in seen:
                continue
            seen.add(key)
            digest = sha256(statement.encode("utf-8")).hexdigest()[:12]
            source_claim_id = f"curated-{request.source_round}-{index}"
            card = LemmaCard(
                lemma_id=(
                    f"{request.plan_id}::lemma::{source_claim_id}-{digest}"
                ),
                statement=statement,
                conditions=_string_items(item["conditions"], "conditions"),
                dependencies=_string_items(
                    item["dependencies"],
                    "dependencies",
                ),
                proof_sketch=str(item["proof_sketch"]).strip(),
                status="provisional",
                evidence_ids=[],
                source_round=request.source_round,
                source_candidate_id=request.plan_id,
                source_claim_id=source_claim_id,
                claim_kind="unknown",
                check_spec=None,
                target_obligation_ids=_string_items(
                    item["target_obligation_ids"],
                    "target_obligation_ids",
                ),
            )
            card.validate()
            cards.append(card)
        return tuple(cards)

    @staticmethod
    def _complete_protocol(response: str, budget: CallBudget) -> None:
        runtime = budget.agent_runtime
        turn_id = str(getattr(response, "protocol_turn_id", ""))
        if runtime is None or not turn_id:
            return
        truncated = bool(
            getattr(response, "output_budget_exceeded", False)
            or str(getattr(response, "finish_reason", "")).casefold()
            == "length"
        )
        reason = (
            "finish_reason_length"
            if str(getattr(response, "finish_reason", "")).casefold() == "length"
            else "observed_output_exceeded_contract"
            if getattr(response, "output_budget_exceeded", False)
            else ""
        )
        lineage = runtime.complete_model_turn(
            turn_id,
            str(response),
            agent_action_protocol=True,
            response_truncated=truncated,
            truncation_reason=reason,
        )
        call_index = getattr(response, "model_call_index", None)
        if call_index is not None:
            budget.record_model_call_lineage(call_index, lineage)

    @staticmethod
    def _fail_protocol(
        response: str,
        budget: CallBudget,
        failure_code: str,
    ) -> None:
        runtime = budget.agent_runtime
        turn_id = str(getattr(response, "protocol_turn_id", ""))
        if runtime is not None and turn_id:
            runtime.fail_model_turn(turn_id, failure_code)


def _string_items(value, name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"Lemma {name} must be a string list")
    return [item.strip() for item in value if item.strip()]


class LemmaCurator:
    """Deterministic host-side Claim-to-Lemma transformation, not an LLM role."""

    def curate(
        self,
        candidates: list[CandidateSolution],
        *,
        round_id: int,
        excluded_statements: set[str] | None = None,
        obligations: dict[str, list[ProofObligation]] | None = None,
        target: str = "",
    ) -> list[LemmaCard]:
        excluded = excluded_statements or set()
        unresolved = [
            obligation
            for items in (obligations or {}).values()
            for obligation in items
            if obligation.required and obligation.status != "satisfied"
        ]
        cards: list[LemmaCard] = []
        seen: set[str] = set()
        for candidate in candidates:
            for claim in candidate.claims:
                statement_key = " ".join(claim.statement.lower().split())
                if not statement_key or statement_key in seen or statement_key in excluded:
                    continue
                target_obligation_ids = _target_obligations(
                    claim.claim_id,
                    claim.claim_kind,
                    claim.statement,
                    unresolved,
                    target,
                )
                if (
                    (unresolved or target)
                    and not target_obligation_ids
                    and claim.importance != "critical"
                    and not _overlap(claim.statement, target)
                ):
                    continue
                seen.add(statement_key)
                digest = sha256(statement_key.encode("utf-8")).hexdigest()[:12]
                dependencies = [
                    namespaced_claim_id(candidate.candidate_id, claim_id)
                    for claim_id in claim.depends_on
                ]
                card = LemmaCard(
                        lemma_id=(
                            f"{candidate.candidate_id}::lemma::{claim.claim_id}-{digest}"
                        ),
                        statement=claim.statement,
                        conditions=list(candidate.assumptions),
                        dependencies=dependencies,
                        proof_sketch=(
                            "Reuse the verified source Claim toward the named "
                            "problem-local target obligations."
                        ),
                        status="provisional",
                        evidence_ids=[],
                        source_round=round_id,
                        source_candidate_id=candidate.candidate_id,
                        source_claim_id=claim.claim_id,
                        claim_kind=claim.claim_kind,
                        check_spec=claim.check_spec,
                        target_obligation_ids=target_obligation_ids,
                    )
                card.validate()
                cards.append(card)
        return cards


def _target_obligations(
    claim_id: str,
    claim_kind: str,
    statement: str,
    obligations: list[ProofObligation],
    target: str,
) -> list[str]:
    scored: list[tuple[int, str]] = []
    for obligation in obligations:
        score = 0
        if claim_id in obligation.source_claim_ids:
            score += 100
        if claim_kind != "unknown" and claim_kind == obligation.kind:
            score += 40
        score += len(_overlap(statement, obligation.description))
        if score > 0:
            scored.append((score, obligation.obligation_id))
    scored.sort(key=lambda item: (-item[0], item[1]))
    if not scored and _overlap(statement, target) and obligations:
        scored.append((1, obligations[0].obligation_id))
    return [obligation_id for _, obligation_id in scored[:4]]


def _overlap(left: str, right: str) -> set[str]:
    if not left or not right:
        return set()
    return {
        item.casefold() for item in _TOKEN.findall(left)
    }.intersection(item.casefold() for item in _TOKEN.findall(right))
