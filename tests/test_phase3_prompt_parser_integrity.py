from __future__ import annotations

import json
import re

import pytest

from mathforge.agents.prompt_compiler import PromptCompiler
from mathforge.agents.registry import PromptContractLoader, SkillRegistry
from mathforge.agents.router_planner import RouterRuleEngine
from mathforge.agents.solver import PrimarySolver, SolverExecutor, SolverRequest
from mathforge.harness.budget import CallBudget
from mathforge.harness.context_budget import InternS2TokenCounter
from mathforge.harness.provider import ModelCallGate, OfficialClientProvider
from mathforge.output.deterministic_formatter import DeterministicFormatter
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.parsing.solution_parser import (
    SolutionParser,
    candidate_response_integrity,
    candidate_response_validation,
)
from mathforge.tools.registry import ToolRegistry, run_tool_direct


def _candidate_payload(method: str, *, solution_text: str = "A public derivation.") -> dict:
    return {
        "method": method,
        "final_answer": "2",
        "public_solution_steps": ["Derive the result from the stated conditions."],
        "claims": [
            {
                "claim_id": "c1",
                "statement": "The requested result equals 2.",
                "depends_on": [],
                "check_type": "reasoning",
                "importance": "critical",
            }
        ],
        "method_steps": [
            {
                "step_id": "s1",
                "kind": "conclusion",
                "claim_ids": ["c1"],
                "theorem": "",
            }
        ],
        "solution_text": solution_text,
        "assumptions": [],
        "theorems": [],
        "unresolved_obligations": [],
    }


class _CompilerAwareClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def chat(self, *, messages, temperature, max_tokens):
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        match = re.search(
            r"Required core method family: ([a-z-]+)\.",
            messages[-1]["content"],
        )
        assert match is not None
        return json.dumps(_candidate_payload(match.group(1)))


class _BrokenTokenizer:
    def apply_chat_template(self, *_args, **_kwargs):
        raise RuntimeError("offline")

    def encode(self, *_args, **_kwargs):
        raise RuntimeError("offline")


def test_simple_production_prompt_is_well_below_the_previous_fallback_size():
    problem = ProblemParser().parse("Compute 17+28.")
    route = RouterRuleEngine().plan(problem)
    skills = SkillRegistry().compose_for_role(
        route.selected_skills,
        max_chars=6000,
        role="PrimarySolver",
    ).text
    request = SolverRequest(
        "simple",
        problem,
        route,
        skills,
        route.method_families[0],
    )

    compilation = PrimarySolver().compile_prompt(request)
    fallback_tokens = InternS2TokenCounter(
        _BrokenTokenizer()
    ).count_messages(compilation.messages).tokens
    static_system_chars = len(
        PromptContractLoader().system_prompt("primary_solver")
    )

    assert compilation.profile == "minimal"
    assert fallback_tokens < 6000
    assert fallback_tokens < 9500 * 0.65
    assert compilation.max_output_tokens == 2048
    assert len(compilation.messages[0]["content"]) < 4000
    assert static_system_chars < len(compilation.messages[0]["content"])


@pytest.mark.parametrize(
    ("problem_text", "expected_profile", "expected_tokens"),
    [
        ("Compute 17+28.", "minimal", 2048),
        ("Prove that x^2 >= 0 for every real x.", "proof", 40960),
        (
            "Given a probability density f(x)=1/2 on [0,2], "
            "verify normalization and compute the probability.",
            "tool",
            32768,
        ),
        (
            "Given matrix [[1,2],[3,4]], compute its determinant.",
            "tool",
            32768,
        ),
    ],
)
def test_representative_profiles_generate_complete_candidates_three_times(
    problem_text,
    expected_profile,
    expected_tokens,
):
    parser = ProblemParser()
    problem = parser.parse(problem_text)
    route = RouterRuleEngine().plan(problem)
    client = _CompilerAwareClient()
    solver = PrimarySolver()
    request = SolverRequest(
        "representative",
        problem,
        route,
        "",
        route.method_families[0],
    )
    assert solver.compile_prompt(request).profile == expected_profile

    for repetition in range(3):
        candidate = SolverExecutor(
            OfficialClientProvider(client, ModelCallGate(1)),
            SolutionParser(),
        ).execute(
            solver,
            SolverRequest(
                f"representative-{repetition}",
                problem,
                route,
                "",
                route.method_families[0],
            ),
            CallBudget(1),
            temperature=0.0,
            max_tokens=65536,
        )
        assert candidate_response_integrity(candidate) == "complete"
        assert candidate_response_validation(candidate) == (
            "strict_candidate_json",
            False,
        )
        assert candidate.claims
        assert candidate.method_steps
        assert candidate.public_solution_steps

    assert [call["max_tokens"] for call in client.calls] == [
        expected_tokens,
        expected_tokens,
        expected_tokens,
    ]


def test_compiler_uses_minimal_candidate_schema_and_caps_non_solver_roles():
    problem = ProblemParser().parse("Compute 1+1.")
    route = RouterRuleEngine().plan(problem)
    compilation = PrimarySolver().compile_prompt(
        SolverRequest(
            "ordered",
            problem,
            route,
            "",
            route.method_families[0],
        )
    )
    system = compilation.messages[0]["content"]

    assert set(compilation.output_schema_fields) == {"answer", "check"}
    assert '{"answer":"<exact answer>","check":"<one concise check>"}' in system
    assert "The Host generates Candidate, Claim, method-step" in system
    assert "solution_text" not in system
    assert "unresolved_obligations" not in system

    compiler = PromptCompiler()
    assert compiler.compile_role(
        "router_planner",
        user_content="Problem: x",
    ).max_output_tokens == 8192
    assert compiler.compile_role(
        "verifier_skeptic",
        user_content="Batch: {}",
    ).max_output_tokens == 16384
    assert compiler.compile_role(
        "repair",
        user_content="Affected claim: c1",
    ).max_output_tokens == 24576


def test_parser_distinguishes_all_response_integrity_classes():
    parser = SolutionParser()
    samples = {
        "complete": json.dumps(_candidate_payload("direct-deduction")),
        "schema_violation": '{"final_answer":"2"}',
        "truncated": '{"method":"direct-deduction","final_answer":"2"',
        "malformed": '{"method":direct-deduction}',
        "natural_language": "Final answer: 2",
        "empty": "",
    }
    expected_validation = {
        "complete": ("strict_candidate_json", False),
        "schema_violation": ("candidate_schema_invalid", True),
        "truncated": ("candidate_json_incomplete", False),
        "malformed": ("candidate_json_invalid", True),
        "natural_language": ("answer_recovered_candidate", False),
        "empty": ("empty_response", True),
    }

    for expected_integrity, response in samples.items():
        candidate = parser.parse(
            response,
            candidate_id=expected_integrity,
            role="PrimarySolver",
            answer_type="expression",
        )
        assert candidate_response_integrity(candidate) == expected_integrity
        assert candidate_response_validation(candidate) == expected_validation[
            expected_integrity
        ]


def test_solution_json_wrapper_is_rejected_before_final_response_formatting():
    parser = SolutionParser()
    wrapped = parser.parse(
        json.dumps(
            _candidate_payload(
                "direct-deduction",
                solution_text='{"final_response":"leaked wrapper"}',
            )
        ),
        candidate_id="wrapped",
        role="PrimarySolver",
        answer_type="expression",
    )

    assert "solution_text:json_wrapper" in wrapped.contract_deviations
    assert candidate_response_validation(wrapped) == (
        "candidate_schema_invalid",
        True,
    )

    clean = parser.parse(
        json.dumps(_candidate_payload("direct-deduction")),
        candidate_id="clean",
        role="PrimarySolver",
        answer_type="expression",
    )
    final_response = DeterministicFormatter().format(
        clean,
        ProblemParser().parse("Compute 1+1."),
    )
    assert not final_response.lstrip().startswith("{")
    assert '"final_response"' not in final_response
    assert '"method"' not in final_response


def test_every_tool_claim_example_is_precise_and_executable():
    registry = ToolRegistry()
    examples = registry.claim_prompt_examples(registry.names(), limit=100)

    assert {example["tool"] for example in examples} == set(
        registry.claimable_names()
    )
    for example in examples:
        claim = example["claim"]
        assert claim["check_type"] == example["tool"]
        assert claim["statement"].strip()
        assert example["invalid_claim"].strip()
        result = run_tool_direct(
            example["tool"],
            example["host_arguments"],
        )
        assert result.status in {"pass", "fail", "unknown"}


def test_tool_profile_names_authorized_checks_but_keeps_arguments_host_owned():
    problem = ProblemParser().parse(
        "Given matrix [[1,2],[3,4]], compute its determinant."
    )
    route = RouterRuleEngine().plan(problem)
    compilation = PrimarySolver().compile_prompt(
        SolverRequest(
            "tool",
            problem,
            route,
            "",
            route.method_families[0],
        )
    )
    system = compilation.messages[0]["content"]

    assert compilation.profile == "tool"
    assert "matrix_shape_check" in system
    assert '"host_arguments"' not in system
    assert "Do not emit tool arguments or calls" in system
