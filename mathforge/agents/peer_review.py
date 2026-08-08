from __future__ import annotations

from dataclasses import dataclass, replace
import json

from mathforge.agent_runtime.protocol import AgentTurnPayloadParser
from mathforge.agents.prompt_compiler import PromptCompiler
from mathforge.agents.registry import PromptContractLoader
from mathforge.harness.budget import CallBudget
from mathforge.harness.errors import ModelResponseError
from mathforge.harness.provider import OfficialClientProvider
from mathforge.harness.schemas import CandidateSolution, ProblemIR, ProofObligation
from mathforge.verification.peer_review import PeerReviewRecord, RebuttalRecord


@dataclass(frozen=True)
class PeerReviewOutcome:
    record: PeerReviewRecord
    turn_id: str
    artifact_id: str
    message_id: str
    thread_id: str


@dataclass(frozen=True)
class RebuttalOutcome:
    record: RebuttalRecord
    turn_id: str
    artifact_id: str
    message_id: str
    thread_id: str


class SolverPeerReviewAgent:
    """Runs Solver-authored review and rebuttal Turns through the official client."""

    def __init__(
        self,
        provider: OfficialClientProvider,
        contracts: PromptContractLoader | None = None,
    ) -> None:
        self._provider = provider
        self._compiler = PromptCompiler(contracts or PromptContractLoader())

    def review(
        self,
        *,
        problem: ProblemIR,
        candidate: CandidateSolution,
        candidate_artifact_id: str,
        author_agent_id: str,
        reviewer_agent_id: str,
        reviewer_role: str,
        reviewer_candidate_id: str,
        obligations: list[ProofObligation],
        budget: CallBudget,
        max_tokens: int,
    ) -> PeerReviewOutcome:
        role_directory = _role_directory(reviewer_role)
        payload = {
            "problem": problem.normalized_problem,
            "response_mode": problem.response_mode,
            "candidate": _public_candidate(candidate),
            "obligations": [item.to_dict() for item in obligations],
            "review_focus": (
                "Check the final answer, every critical Claim, theorem conditions, "
                "missing cases, and attempt a counterexample."
            ),
        }
        compilation = self._compiler.compile_solver_collaboration(
            role_directory,
            user_content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            mode="peer_review",
        )
        response = self._call(
            compilation.messages,
            reviewer_role=reviewer_role,
            reviewer_candidate_id=reviewer_candidate_id,
            input_artifact_id=candidate_artifact_id,
            budget=budget,
            max_tokens=min(max_tokens or compilation.max_output_tokens, compilation.max_output_tokens),
        )
        parsed = self._parse(response, "challenge_candidate", "PeerReviewArtifact")
        turn_id = str(getattr(response, "protocol_turn_id", ""))
        review_id = f"review-{turn_id}" if turn_id else f"review-{candidate.candidate_id}-{reviewer_role}"
        try:
            record = PeerReviewRecord.from_model_payload(
                parsed.result_payload,
                review_id=review_id,
                reviewer_agent_id=reviewer_agent_id,
                author_agent_id=author_agent_id,
                candidate=candidate,
                candidate_artifact_id=candidate_artifact_id,
                source_turn_id=turn_id,
                obligation_ids={item.obligation_id for item in obligations},
            )
            lineage = self._complete(response, budget)
        except Exception as error:
            self._fail(response, budget, "peer_review_payload_invalid")
            raise ModelResponseError("peer_review_payload_invalid") from error
        record = replace(
            record,
            artifact_id=lineage.get("output_artifact_id", ""),
            message_id=lineage.get("message_id", ""),
        )
        return PeerReviewOutcome(
            record,
            turn_id,
            record.artifact_id,
            record.message_id,
            lineage.get("thread_id", ""),
        )

    def rebut(
        self,
        *,
        candidate: CandidateSolution,
        review: PeerReviewRecord,
        author_agent_id: str,
        reviewer_agent_id: str,
        author_role: str,
        author_candidate_id: str,
        budget: CallBudget,
        max_tokens: int,
    ) -> RebuttalOutcome:
        role_directory = _role_directory(author_role)
        payload = {
            "candidate": _public_candidate(candidate),
            "peer_review": review.to_dict(),
            "instruction": (
                "Respond to each Finding using only published Claims/evidence. "
                "Defend, clarify, or explicitly concede; do not repair the Candidate."
            ),
        }
        compilation = self._compiler.compile_solver_collaboration(
            role_directory,
            user_content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            mode="respond_to_review",
        )
        response = self._call(
            compilation.messages,
            reviewer_role=author_role,
            reviewer_candidate_id=author_candidate_id,
            input_artifact_id=review.artifact_id,
            budget=budget,
            max_tokens=min(max_tokens or compilation.max_output_tokens, compilation.max_output_tokens),
        )
        parsed = self._parse(response, "publish_rebuttal", "RebuttalArtifact")
        turn_id = str(getattr(response, "protocol_turn_id", ""))
        rebuttal_id = f"rebuttal-{turn_id}" if turn_id else f"rebuttal-{review.review_id}"
        try:
            record = RebuttalRecord.from_model_payload(
                parsed.result_payload,
                rebuttal_id=rebuttal_id,
                author_agent_id=author_agent_id,
                reviewer_agent_id=reviewer_agent_id,
                candidate=candidate,
                review=review,
                source_turn_id=turn_id,
            )
            lineage = self._complete(response, budget)
        except Exception as error:
            self._fail(response, budget, "rebuttal_payload_invalid")
            raise ModelResponseError("rebuttal_payload_invalid") from error
        record = replace(
            record,
            artifact_id=lineage.get("output_artifact_id", ""),
            message_id=lineage.get("message_id", ""),
        )
        return RebuttalOutcome(
            record,
            turn_id,
            record.artifact_id,
            record.message_id,
            lineage.get("thread_id", ""),
        )

    def _call(
        self,
        messages: list[dict[str, str]],
        *,
        reviewer_role: str,
        reviewer_candidate_id: str,
        input_artifact_id: str,
        budget: CallBudget,
        max_tokens: int,
    ) -> str:
        stage = "primary" if reviewer_role == "PrimarySolver" else "alternative"
        budget.consume(
            stage=stage,
            optional=False,
            action_category="peer_review_response",
        )
        budget.record_prompt_chars(sum(len(item["content"]) for item in messages))
        return self._provider.chat(
            messages=messages,
            temperature=0.0,
            max_tokens=max_tokens,
            budget=budget,
            stage=stage,
            turn_kind="peer_review",
            agent_id=f"{reviewer_role}:{reviewer_candidate_id}",
            agent_action_protocol=True,
            input_artifact_ids=(input_artifact_id,),
        )

    @staticmethod
    def _parse(response: str, action: str, artifact_type: str):
        try:
            parsed = AgentTurnPayloadParser().parse(
                response,
                allowed_actions=(action,),
            )
        except (TypeError, ValueError) as error:
            raise ModelResponseError("collaboration_turn_payload_invalid") from error
        if parsed.payload.task_result_type != artifact_type:
            raise ModelResponseError("collaboration_turn_result_type_invalid")
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


def _role_directory(role: str) -> str:
    if role == "PrimarySolver":
        return "primary_solver"
    if role == "AlternativeSolver":
        return "alternative_solver"
    raise ValueError("peer review must be authored by a Solver")


def _public_candidate(candidate: CandidateSolution) -> dict:
    return {
        "candidate_id": candidate.candidate_id,
        "version": candidate.version,
        "method": candidate.method,
        "final_answer": candidate.final_answer,
        "claims": [item.to_dict() for item in candidate.claims],
        "method_steps": [item.to_dict() for item in candidate.method_steps],
        "public_solution_steps": list(candidate.public_solution_steps),
        "assumptions": list(candidate.assumptions),
        "theorems": list(candidate.theorems),
        "unresolved_obligations": list(candidate.unresolved_obligations),
    }
