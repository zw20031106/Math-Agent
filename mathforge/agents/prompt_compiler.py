from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json

from mathforge.agent_runtime.router_protocol import (
    ROUTER_INTENT_FIELDS,
    ROUTER_INTENT_STRUCTURAL_SHAPE,
)
from mathforge.agents.registry import PromptContract, PromptContractLoader
from mathforge.context.errors import ContextBudgetExceeded
from mathforge.harness.model_candidate_contract import (
    MODEL_CANDIDATE_PATCH_STRUCTURAL_SHAPE,
    MODEL_CANDIDATE_PAYLOAD_VERSION,
    MODEL_CANDIDATE_PROFILE_FIELDS,
    MODEL_CANDIDATE_STRUCTURAL_SHAPE,
)
from mathforge.harness.model_policy import stage_output_cap
from mathforge.harness.schemas import ProblemIR, RoutePlan
_ROLE_DIRECTORY_TO_STAGE = {
    "router_planner": "router",
    "primary_solver": "primary",
    "alternative_solver": "alternative",
    "lemma_curator": "lemma",
    "verifier_skeptic": "verifier",
    "repair": "repair",
    "finalizer": "finalizer",
}
_SOLVER_OUTPUT_TOKENS = {
    "minimal": {
        "primary_solver": 2048,
        "alternative_solver": 2048,
    },
    "standard": {
        "primary_solver": 32768,
        "alternative_solver": 32768,
    },
    "tool": {
        "primary_solver": 32768,
        "alternative_solver": 32768,
    },
    "proof": {
        "primary_solver": 40960,
        "alternative_solver": 40960,
    },
}
_ANSWER_FIRST_PROTOCOL = (
    "Give the final answer first, then the public derivation. Encode the exact "
    "final answer as \\boxed{...}."
)
_AGENT_TURN_ENVELOPE_PROTOCOL = (
    "Wrap the public result in AgentTurnPayload 1.0 with exactly these fields "
    "in this order: protocol_version, task_result_type, action, "
    "public_state_delta, result_payload, outbound_intents, progress_summary, "
    "stop_reason. protocol_version is \"1.0\". Never generate agent_id, "
    "task_id, turn_id, artifact_id, message_id, thread_id, token limits, or "
    "timeouts; the Host owns them. Return one bare JSON object only. "
)
_CANDIDATE_CORE_PROTOCOL = (
    f"Return one bare ModelCandidatePayload {MODEL_CANDIDATE_PAYLOAD_VERSION} "
    "JSON object. Put final_answer first as a string containing "
    "\\boxed{...}; solution_text is the complete public derivation string. "
    "Only those two fields are required. Optional structured fields may be "
    "omitted. JSON-escape every LaTeX backslash. Return no Markdown fence or "
    f"surrounding prose. Shape: {MODEL_CANDIDATE_STRUCTURAL_SHAPE}."
)


def _candidate_profile_protocol(profile: str) -> str:
    shared = _CANDIDATE_CORE_PROTOCOL + " "
    if profile == "simple":
        return shared + "Keep solution_text to one concise public check."
    if profile == "proof":
        return shared + (
            "solution_text must contain the complete ordered public proof and "
            "every genuinely unresolved hypothesis."
        )
    return shared + (
        "solution_text must contain one non-redundant ordered public derivation."
    )
_PROGRESS_DELTA_PROTOCOL = (
    "Public protocol mode is {mode}. Construct one ProgressDelta object with "
    "these nine fields and no others: public_summary, strategy, subgoals, "
    "claims, open_obligations, closed_obligation_ids, contradictions, "
    "next_step, stop_reason. This is a public, auditable ProgressDelta, not a "
    "final Candidate response. public_summary, strategy, "
    "next_step, and stop_reason are strings. subgoals is an array of objects "
    "with exactly subgoal_id, statement, depends_on, exit_condition, status; "
    "status is open, active, closed, or blocked. claims is an array of objects "
    "with exactly claim_id, statement, depends_on, subgoal_ids, importance, "
    "check_type; importance is critical or supporting. check_type is only a "
    "suggestion from the authorized check list; the Host owns typed check_spec "
    "and all tool arguments. open_obligations is an array of "
    "objects with exactly obligation_id, statement, depends_on, where "
    "depends_on references public Claim ids. closed_obligation_ids and "
    "contradictions are string arrays. Reuse existing ids without rewriting "
    "their content. Add only atomic, publicly checkable mathematical claims. "
    "Do not emit a final answer, CandidateSolution, tool call, raw model "
    "response, or Host-owned state/version fields. "
    'Use this exact shape: {"public_summary":"<public progress>",'
    '"strategy":"<current method>","subgoals":[{"subgoal_id":"g1",'
    '"statement":"<public target>","depends_on":[],"exit_condition":'
    '"<observable closure>","status":"open"}],"claims":[{"claim_id":'
    '"r1-c1","statement":"<atomic public claim>","depends_on":[],'
    '"subgoal_ids":["g1"],"importance":"supporting"}],'
    '"open_obligations":[{"obligation_id":"o1","statement":'
    '"<condition to establish>","depends_on":["r1-c1"]}],'
    '"closed_obligation_ids":[],"contradictions":[],"next_step":'
    '"<one bounded action>","stop_reason":""}.'
)
_PEER_REVIEW_PROTOCOL = (
    _AGENT_TURN_ENVELOPE_PROTOCOL
    + "Public protocol mode is peer_review. Use task_result_type "
    "PeerReviewArtifact and action challenge_candidate. Put exactly these "
    "fields in result_payload: finding_items, answer_assessment, "
    "method_overlap_assessment, missing_conditions, counterexample_attempts, "
    "unresolved_obligations, recommended_action, stop_reason. finding_items "
    "must be a non-empty array. Every item must contain exactly finding_id, "
    "candidate_id, claim_id, method_step_id, obligation_ids, status, "
    "public_rationale, missing_condition, counterexample_summary, severity. "
    "Cite the exact supplied candidate_id and a real supplied claim_id. status "
    "is pass, fail, or unknown; severity is info, warning, error, or critical. "
    "Use public_state_delta {} and outbound_intents []. Review the Candidate; "
    "do not rewrite it or generate a replacement answer."
)
_REBUTTAL_PROTOCOL = (
    _AGENT_TURN_ENVELOPE_PROTOCOL
    + "Public protocol mode is respond_to_review. Use task_result_type "
    "RebuttalArtifact and action publish_rebuttal. Put exactly responses and "
    "stop_reason in result_payload. responses is non-empty; each item contains "
    "exactly finding_id, response, action, supporting_claim_ids, evidence_refs, "
    "requested_followup. Cite only supplied Finding and Claim ids. action is "
    "defend, clarify, or concede. A concession must be explicit; do not silently "
    "repair or rewrite the Candidate in F5. Use public_state_delta {} and "
    "outbound_intents []. Add only public content that responds to the Finding "
    "without repeating the debate."
)
_CROSS_EXAM_PROTOCOL = (
    _AGENT_TURN_ENVELOPE_PROTOCOL
    + "Public protocol mode is cross_exam. Use task_result_type "
    "CritiqueArtifact and action challenge_candidate. Put exactly findings, "
    "peer_review_assessments, uncovered_goal_ids, recommended_action, and "
    "stop_reason in result_payload. Every Finding contains exactly finding_id, "
    "candidate_id, claim_id, obligation_ids, peer_finding_ids, status, scope, "
    "actionability, public_rationale, missing_condition, and "
    "counterexample_summary. status is pass, fail, or unknown; scope is local, "
    "global, or review; actionability is retain, local_repair, new_branch, "
    "replan, reject, or continue_review. A local failure must cite a supplied "
    "Claim. A global method failure must never be presented as local_repair. "
    "peer_review_assessments must assess every supplied Peer Finding using "
    "exactly finding_id, status, and public_rationale; finding_id must equal "
    "the supplied finding_ref (which is qualified when raw Finding ids collide). "
    "Use peer_finding_ids to cite those same supplied finding_ref values. "
    "Use public_state_delta {} and outbound_intents []. Do not repair, solve, "
    "or arbitrate."
)
_FINAL_AUDIT_PROTOCOL = (
    _AGENT_TURN_ENVELOPE_PROTOCOL
    + "Public protocol mode is final_audit. Use task_result_type AuditArtifact "
    "and action complete. Put exactly candidate_id, candidate_version, status, "
    "open_finding_ids, open_obligation_ids, reviewed_artifact_ids, "
    "reviewed_finding_ids, reviewed_obligation_ids, "
    "requested_action, public_rationale, and stop_reason in result_payload. "
    "status is complete_hard, complete_audited, incomplete, or failed. "
    "requested_action is retain, local_repair, new_branch, replan, reject, or "
    "continue_review. Cite only supplied IDs and only the supplied final active "
    "Candidate version. Copy every supplied audit_requirements required id into "
    "the matching reviewed list after checking it. A complete status has no "
    "open Finding or obligation and covers every required item. "
    "Use public_state_delta {} and outbound_intents []. Audit only: do not "
    "rewrite, polish, repair, or generate an answer and do not expose private "
    "reasoning."
)
_REPAIR_PATCH_PROTOCOL = (
    "Return exactly one bare JSON object containing replacement_claims, "
    "final_answer, public_solution_steps, and unresolved_obligations. "
    "replacement_claims contains only affected Claim replacements, each with "
    "exactly claim_id, statement, depends_on, check_type, and importance. "
    "Do not return method, method_steps, solution_text, unrelated Claims, or "
    "Host-owned fields. The Host applies the patch to the prior Candidate, "
    "re-verifies the affected dependency closure, and rolls back regressions. "
    "Use this exact structural shape: "
    f"{MODEL_CANDIDATE_PATCH_STRUCTURAL_SHAPE}. Delimit formulas in public "
    "steps and Claim statements with $...$; keep final_answer free of $ "
    "delimiters."
)
_ROLE_PROTOCOLS = {
    "router_planner": (
        "Return only RouterIntent JSON. The Host owns subgoals, the task DAG, "
        "Agent assignment, Candidate count, priorities, resources, and plan "
        f"versions. Use exactly this shape: {ROUTER_INTENT_STRUCTURAL_SHAPE}."
    ),
    "lemma_curator": (
        _AGENT_TURN_ENVELOPE_PROTOCOL
        + "Use task_result_type LemmaArtifact and action complete. Put exactly "
        "one object in result_payload with field lemmas. lemmas is an array; "
        "each item contains exactly statement, conditions, dependencies, "
        "proof_sketch, and target_obligation_ids. Proposed lemmas are public "
        "targets, not verified facts. Use public_state_delta as {} and a "
        "non-empty progress_summary and stop_reason. outbound_intents must "
        "contain exactly the public "
        "recipient_role supplied by the Host and no IDs. Do not solve or "
        "arbitrate the final answer."
    ),
    "verifier_skeptic": (
        "Return only one JSON object with findings. Each finding contains "
        "candidate_id, claim_id, obligation_ids, review_target_ids, "
        "review_level, status, public_rationale, missing_condition, and "
        "counterexample_summary. Status is pass, fail, or unknown. An "
        "obligation pass must cite a real Claim and supported obligation. An "
        "answer- or claim-level pass must cite a real Claim and supplied review "
        "target. Review only supplied Claim-linked public segments; unknown is "
            "not pass. Do not reconstruct full solutions."
    ),
    "repair": (
        f"{_REPAIR_PATCH_PROTOCOL} Change only the supplied failed Claim "
        "dependency closure. Preserve the exact final answer unless the affected "
        "terminal Claim proves it must change."
    ),
    "finalizer": (
        f"{_CANDIDATE_CORE_PROTOCOL} Normalize presentation only. Preserve the "
        "method, public exposition, verified Claims, assumptions, theorems, open "
        "obligations, and exact final answer; introduce no new mathematical content."
    ),
}


@dataclass(frozen=True)
class PromptCompilation:
    profile: str
    messages: list[dict[str, str]]
    max_output_tokens: int
    prompt_chars: int
    output_schema_fields: tuple[str, ...] = ()
    prompt_sha256: str = ""
    contract_sha256: str = ""


@dataclass(frozen=True)
class PromptSpec:
    role_directory: str
    profile: str
    contract: PromptContract
    runtime_protocol: str
    output_schema_fields: tuple[str, ...] = ()

    def system_prompt(self) -> str:
        return self.contract.render_system(self.runtime_protocol)


class PromptCompiler:
    """Compile concise role/problem-specific prompts from immutable contracts."""

    def __init__(
        self,
        contracts: PromptContractLoader | None = None,
    ) -> None:
        self._contracts = contracts or PromptContractLoader()

    def compile_solver(
        self,
        role_directory: str,
        *,
        problem: ProblemIR,
        route: RoutePlan,
        user_content: str,
        runtime_instructions: str = "",
        autonomous: bool = False,
        compact: bool = False,
    ) -> PromptCompilation:
        if role_directory not in {"primary_solver", "alternative_solver"}:
            raise ValueError("solver prompt role is invalid")
        profile = self.solver_profile(problem, route)
        output_profile = self.candidate_output_profile(problem, route)
        instructions = [
            _candidate_profile_protocol(output_profile),
            self._response_mode_protocol(problem),
            self._solver_profile_protocol(profile),
        ]
        if autonomous:
            instructions.insert(
                0,
                _AGENT_TURN_ENVELOPE_PROTOCOL
                + "For a complete solution use task_result_type "
                "CandidateArtifact and action publish_candidate; place the "
                f"entire {output_profile} Candidate object inside result_payload, set "
                "public_state_delta to {}, and use outbound_intents []. If no "
                "sound candidate can be produced, use action abstain, "
                "task_result_type CheckpointArtifact, empty result_payload, "
                "and explain the public reason in stop_reason. "
            )
        else:
            instructions.insert(
                0,
                "Return the ModelCandidatePayload as exactly one complete bare "
                "JSON object, with no prose or Markdown fence.",
            )
        if compact:
            instructions.append(
                "This is compact_synthesis recovery. Consume only the supplied "
                "verified public Artifact summaries. Return the smallest complete "
                "Candidate object; do not repeat the discarded long response."
            )
        if role_directory == "alternative_solver":
            instructions.append(
                "Solve independently from the forbidden method families; do not "
                "reconstruct or imitate a Primary solution."
            )
        if profile == "tool":
            tools = self._prioritized_tools(route.selected_tools)
            if tools:
                instructions.append(
                    "Make the public steps explicit enough for the Host to derive "
                    "safe deterministic checks for these authorized tools: "
                    + ", ".join(tools[:3])
                    + ". Do not emit tool arguments or calls."
                )
        if runtime_instructions.strip():
            instructions.append(runtime_instructions.strip())
        output_tokens = _SOLVER_OUTPUT_TOKENS[profile][role_directory]
        instructions.append(
            f"This Candidate Turn has a {output_tokens:,}-token output ceiling; "
            "this is a per-Turn ceiling, not a per-problem reasoning budget."
        )
        instructions.append(_ANSWER_FIRST_PROTOCOL)
        return self._compile(
            role_directory,
            profile,
            user_content,
            "\n".join(instructions),
            output_tokens,
            output_schema_fields=tuple(
                sorted(MODEL_CANDIDATE_PROFILE_FIELDS[output_profile])
            ),
        )

    def compile_solver_progress(
        self,
        role_directory: str,
        *,
        problem: ProblemIR,
        route: RoutePlan,
        user_content: str,
        mode: str,
        runtime_instructions: str = "",
        autonomous: bool = False,
    ) -> PromptCompilation:
        if role_directory not in {"primary_solver", "alternative_solver"}:
            raise ValueError("solver progress prompt role is invalid")
        if mode not in {"explore", "continue"}:
            raise ValueError("progress mode must be explore or continue")
        profile = self.solver_profile(problem, route)
        instructions = [_PROGRESS_DELTA_PROTOCOL.replace("{mode}", mode)]
        if autonomous:
            instructions.insert(
                0,
                _AGENT_TURN_ENVELOPE_PROTOCOL
                + "Use task_result_type ProgressArtifact. Put the exact "
                "ProgressDelta object inside public_state_delta and use empty "
                "result_payload. Choose one action: continue_reasoning, "
                "request_lemma, request_tool_check, request_replan, complete, "
                "or abstain. Use complete with a non-empty stop_reason when the "
                "public exploration is ready for a separate Candidate synthesis "
                "Turn. "
                "For a request action include one matching outbound_intent with "
                "only public request details and Artifact-independent Claim or "
                "obligation references. For continue_reasoning use [] intents. "
                "A continuation must add a Claim, Subgoal, obligation transition, "
                "or concrete request; wording-only changes are invalid. Use "
                "task_result_type ToolRequestArtifact for request_tool_check, "
                "CheckpointArtifact for abstain, and ProgressArtifact otherwise."
            )
        else:
            instructions.insert(
                0,
                "Return the ProgressDelta as exactly one complete bare JSON "
                "object, with no prose or Markdown fence.",
            )
        if mode == "explore":
            instructions.append(
                "Decompose the exact target and establish the first useful "
                "public Claims. Preserve every stated condition, definition, "
                "quantifier, and target from ProblemFrame."
            )
        else:
            instructions.append(
                "Consume only the supplied public ReasoningState. Advance one "
                "or a small number of open Subgoals; explicitly close or retain "
                "obligations and do not repeat unchanged state."
            )
        if runtime_instructions.strip():
            instructions.append(runtime_instructions.strip())
        return self._compile(
            role_directory,
            f"{profile}:{mode}",
            user_content,
            "\n".join(instructions),
            12288,
            output_schema_fields=(
                "claims",
                "closed_obligation_ids",
                "contradictions",
                "next_step",
                "open_obligations",
                "public_summary",
                "stop_reason",
                "strategy",
                "subgoals",
            ),
        )

    def compile_emergency_answer(
        self,
        *,
        problem: ProblemIR,
        user_content: str,
    ) -> PromptCompilation:
        instructions = "\n".join(
            (
                _candidate_profile_protocol("simple"),
                self._response_mode_protocol(problem),
                "This is the final gradeability fallback. Solve the problem "
                "directly and return the exact scorer-facing answer plus one "
                "short public check. Do not emit an AgentTurn envelope.",
                _ANSWER_FIRST_PROTOCOL,
            )
        )
        return self._compile(
            "primary_solver",
            "emergency_direct",
            user_content,
            instructions,
            2048,
            output_schema_fields=tuple(
                sorted(MODEL_CANDIDATE_PROFILE_FIELDS["simple"])
            ),
        )

    def compile_solver_collaboration(
        self,
        role_directory: str,
        *,
        user_content: str,
        mode: str,
    ) -> PromptCompilation:
        if role_directory not in {"primary_solver", "alternative_solver"}:
            raise ValueError("solver collaboration role is invalid")
        if mode == "peer_review":
            protocol = _PEER_REVIEW_PROTOCOL
        elif mode == "respond_to_review":
            protocol = _REBUTTAL_PROTOCOL
        else:
            raise ValueError("solver collaboration mode is invalid")
        return self._compile(
            role_directory,
            mode,
            user_content,
            protocol,
            stage_output_cap("peer_review"),
        )

    def compile_verifier_closure(
        self,
        *,
        user_content: str,
        mode: str,
    ) -> PromptCompilation:
        if mode == "cross_exam":
            protocol = _CROSS_EXAM_PROTOCOL
        elif mode == "final_audit":
            protocol = _FINAL_AUDIT_PROTOCOL
        else:
            raise ValueError("Verifier closure mode is invalid")
        return self._compile(
            "verifier_skeptic",
            mode,
            user_content,
            protocol,
            stage_output_cap("verifier"),
        )

    def compile_role(
        self,
        role_directory: str,
        *,
        user_content: str,
        runtime_instructions: str = "",
    ) -> PromptCompilation:
        protocol = _ROLE_PROTOCOLS.get(role_directory)
        if protocol is None:
            raise ValueError(f"role prompt compiler is unavailable: {role_directory}")
        instructions = protocol
        if runtime_instructions.strip():
            instructions += "\n" + runtime_instructions.strip()
        if role_directory == "finalizer":
            instructions += "\n" + _ANSWER_FIRST_PROTOCOL
        stage = _ROLE_DIRECTORY_TO_STAGE[role_directory]
        return self._compile(
            role_directory,
            stage,
            user_content,
            instructions,
            stage_output_cap(stage),
            output_schema_fields=(
                tuple(sorted(ROUTER_INTENT_FIELDS))
                if role_directory == "router_planner"
                else ()
            ),
        )

    @staticmethod
    def candidate_output_profile(problem: ProblemIR, route: RoutePlan) -> str:
        solver_profile = PromptCompiler.solver_profile(problem, route)
        if solver_profile == "proof":
            return "proof"
        if solver_profile == "minimal":
            return "simple"
        return "standard"

    @staticmethod
    def solver_profile(problem: ProblemIR, route: RoutePlan) -> str:
        if problem.problem_type in {"proof", "derivation"}:
            return "proof"
        specialized_tools = {
            "numerical_residual",
            "matrix_shape_check",
            "density_normalization",
            "small_case_enumeration",
        }
        if specialized_tools.intersection(route.selected_tools):
            return "tool"
        if (
            problem.problem_type in {"calculation", "fill_blank", "multiple_choice"}
            and len(problem.normalized_problem) <= 240
            and len(problem.assumptions) <= 2
            and route.risk_level != "high"
        ):
            return "minimal"
        return "standard"

    @staticmethod
    def bounded_output_tokens(configured: int, compiled: int) -> int:
        if type(configured) is not int or configured < 0:
            raise ValueError("configured output tokens must be nonnegative")
        return compiled if configured == 0 else min(configured, compiled)

    @staticmethod
    def _solver_profile_protocol(profile: str) -> str:
        if profile == "minimal":
            return (
                "Use one direct check. Finish the compact JSON object before any "
                "optional explanation."
            )
        if profile == "proof":
            return (
                "Give a complete ordered proof, state theorem conditions, cover "
                "necessity and sufficiency when applicable, and list every genuinely "
                "open condition explicitly."
            )
        if profile == "tool":
            return (
                "Make each step explicit about expressions, domains, assumptions, "
                "matrix data, intervals, or finite cases so Host checks are safe."
            )
        return (
            "Provide one concise public derivation with explicit conditions; avoid "
            "repeating the problem or protocol."
        )

    @staticmethod
    def _response_mode_protocol(problem: ProblemIR) -> str:
        if problem.response_mode == "proof_full":
            return (
                "Host response mode is proof_full. solution_text must contain the "
                "complete public proof, including essential inferences, theorem "
                "hypotheses, boundary cases, and the conclusion. Compress wording, "
                "not mathematics."
            )
        if problem.response_mode == "worked_solution":
            return (
                "Host response mode is worked_solution. solution_text must be an ordered, "
                "independently checkable complete derivation."
            )
        return (
            "Host response mode is answer_only. Give the exact canonical answer and "
            "the shortest independently checkable public justification in solution_text."
        )

    def _compile(
        self,
        role_directory: str,
        profile: str,
        user_content: str,
        instructions: str,
        output_tokens: int,
        *,
        output_schema_fields: tuple[str, ...] = (),
    ) -> PromptCompilation:
        contract = self._contracts.load(role_directory)
        spec = PromptSpec(
            role_directory=role_directory,
            profile=profile,
            contract=contract,
            runtime_protocol=instructions,
            output_schema_fields=output_schema_fields,
        )
        system = spec.system_prompt()
        prompt_chars = len(system) + len(user_content)
        if prompt_chars > contract.max_context_chars:
            raise ContextBudgetExceeded(
                f"{contract.fields['role']} messages require {prompt_chars} chars, "
                f"budget is {contract.max_context_chars}"
            )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]
        prompt_digest = sha256(
            json.dumps(
                messages,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return PromptCompilation(
            profile=profile,
            messages=messages,
            max_output_tokens=output_tokens,
            prompt_chars=prompt_chars,
            output_schema_fields=output_schema_fields,
            prompt_sha256=prompt_digest,
            contract_sha256=contract.source_sha256,
        )

    @staticmethod
    def _prioritized_tools(tools: list[str]) -> list[str]:
        specialized = {
            "numerical_residual",
            "matrix_shape_check",
            "density_normalization",
            "small_case_enumeration",
        }
        generic = {"answer_type_check", "latex_syntax_check"}
        return [
            *[name for name in tools if name in specialized],
            *[
                name
                for name in tools
                if name not in specialized and name not in generic
            ],
            *[name for name in tools if name in generic],
        ]
