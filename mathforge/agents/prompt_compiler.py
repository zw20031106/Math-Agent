from __future__ import annotations

from dataclasses import dataclass
import json

from mathforge.agents.registry import PromptContract, PromptContractLoader
from mathforge.context.errors import ContextBudgetExceeded
from mathforge.harness.model_policy import stage_output_cap
from mathforge.harness.schemas import ProblemIR, RoutePlan
from mathforge.tool_prompt_examples import claim_prompt_examples


_ROLE_DIRECTORY_TO_STAGE = {
    "router_planner": "router",
    "primary_solver": "primary",
    "alternative_solver": "alternative",
    "verifier_skeptic": "verifier",
    "repair": "repair",
    "finalizer": "finalizer",
}
_SOLVER_OUTPUT_TOKENS = {
    "minimal": {
        "primary_solver": 8192,
        "alternative_solver": 8192,
    },
    "standard": {
        "primary_solver": 16384,
        "alternative_solver": 12288,
    },
    "tool": {
        "primary_solver": 16384,
        "alternative_solver": 16384,
    },
    "proof": {
        "primary_solver": 32768,
        "alternative_solver": 24576,
    },
}
_CANDIDATE_CORE_PROTOCOL = (
    "Return exactly one complete JSON object, with no prose or Markdown fence. "
    "Put the durable core fields first in this order: method, final_answer, "
    "public_solution_steps, claims. Then include method_steps, solution_text, "
    "assumptions, theorems, and unresolved_obligations. All nine fields are "
    "required; list fields may be empty. Copy the assigned method family exactly. "
    "Each method step must reference real Claim IDs. Do not emit Host-owned fields "
    "(candidate_id, role, answer_type, planned_method_family, version, "
    "schema_version, parse_status, is_method_duplicate, contract_deviations, or "
    "Claim verification state). Do not emit tool calls, tool arguments, private "
    "reasoning, scratchpads, or hidden chain-of-thought."
)
_ROLE_PROTOCOLS = {
    "router_planner": (
        "Return only RoutePlan JSON with primary_subject, auxiliary_subject, "
        "risk_level, and exactly three controlled method_families. Do not solve "
        "the problem and do not include a Candidate contract."
    ),
    "verifier_skeptic": (
        "Return only one JSON object with findings. Each finding contains "
        "candidate_id, claim_id, obligation_ids, status, public_rationale, "
        "missing_condition, and counterexample_summary. Status is pass, fail, or "
        "unknown. Pass must cite a real Claim and supported obligation; unknown is "
        "not pass. Do not reconstruct full solutions or emit private reasoning."
    ),
    "repair": (
        f"{_CANDIDATE_CORE_PROTOCOL} Change only the supplied failed Claim "
        "dependency closure. Preserve unrelated content and return a local patch "
        "with the corrected or unchanged exact final answer."
    ),
    "finalizer": (
        f"{_CANDIDATE_CORE_PROTOCOL} Improve public exposition only. Preserve the "
        "verified Claims, assumptions, theorems, and exact final answer; introduce "
        "no new mathematical conclusion."
    ),
}


@dataclass(frozen=True)
class PromptCompilation:
    profile: str
    messages: list[dict[str, str]]
    max_output_tokens: int
    prompt_chars: int


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
    ) -> PromptCompilation:
        if role_directory not in {"primary_solver", "alternative_solver"}:
            raise ValueError("solver prompt role is invalid")
        profile = self.solver_profile(problem, route)
        instructions = [
            _CANDIDATE_CORE_PROTOCOL,
            self._solver_profile_protocol(profile),
        ]
        if role_directory == "alternative_solver":
            instructions.append(
                "Solve independently from the forbidden method families; do not "
                "reconstruct or imitate a Primary solution."
            )
        if profile == "tool":
            examples = claim_prompt_examples(
                self._prioritized_tools(route.selected_tools),
                limit=3,
            )
            if examples:
                instructions.append(
                    "Use precise Claim statements that let the Host reconstruct safe "
                    "tool inputs. These are input-shape examples only; never output "
                    "host_arguments yourself:\n"
                    + json.dumps(
                        examples,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
        if runtime_instructions.strip():
            instructions.append(runtime_instructions.strip())
        output_tokens = _SOLVER_OUTPUT_TOKENS[profile][role_directory]
        return self._compile(
            role_directory,
            profile,
            user_content,
            "\n".join(instructions),
            output_tokens,
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
        stage = _ROLE_DIRECTORY_TO_STAGE[role_directory]
        return self._compile(
            role_directory,
            stage,
            user_content,
            instructions,
            stage_output_cap(stage),
        )

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
                "This is a short problem. Use one to three public steps, Claims, and "
                "method steps. Keep optional lists concise and finish the JSON early."
            )
        if profile == "proof":
            return (
                "Build a complete Claim dependency graph, state theorem conditions, "
                "cover necessity/sufficiency as applicable, and list every unresolved "
                "proof obligation explicitly."
            )
        if profile == "tool":
            return (
                "Make every tool-checkable Claim atomic, explicit about expressions, "
                "domains, assumptions, matrix data, intervals, or finite cases, and "
                "choose the matching check_type."
            )
        return (
            "Provide a complete public derivation with concise Claims and explicit "
            "conditions; avoid repeated restatement of the contract."
        )

    def _compile(
        self,
        role_directory: str,
        profile: str,
        user_content: str,
        instructions: str,
        output_tokens: int,
    ) -> PromptCompilation:
        contract = self._contracts.load(role_directory)
        system = self._system_header(contract) + "\n" + instructions
        prompt_chars = len(system) + len(user_content)
        if prompt_chars > contract.max_context_chars:
            raise ContextBudgetExceeded(
                f"{contract.fields['role']} messages require {prompt_chars} chars, "
                f"budget is {contract.max_context_chars}"
            )
        return PromptCompilation(
            profile=profile,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            max_output_tokens=output_tokens,
            prompt_chars=prompt_chars,
        )

    @staticmethod
    def _system_header(contract: PromptContract) -> str:
        fields = contract.fields
        return "\n".join(
            (
                f"You are {fields['role']}. Follow prompt contract version "
                f"{fields['version']}.",
                f"Objective: {fields['objective']}.",
                f"Visible context only: {fields['visible_memory']}.",
                f"Forbidden context: {fields['forbidden_context']}.",
                f"Allowed tools: {fields['allowed_tools']}.",
                f"Failure policy: {fields['failure_policy']}.",
                f"Stop condition: {fields['stop_condition']}.",
            )
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
