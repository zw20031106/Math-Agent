from __future__ import annotations

from mathforge.agents.registry import PromptContractLoader
from mathforge.harness.schemas import ProblemIR
from mathforge.skills.mechmath_format import (
    COMMON_METHOD_CARD_SECTIONS,
    MECHMATH_SKILL_FORMAT,
)
from mathforge.skills.registry import SkillRegistry
from mathforge.skills.selector import DynamicSkillSelector


_ROLE_DIRECTORIES = (
    "router_planner",
    "primary_solver",
    "alternative_solver",
    "lemma_curator",
    "verifier_skeptic",
    "repair",
    "finalizer",
)


def test_all_prompt_contracts_use_the_role_card_lifecycle_format():
    loader = PromptContractLoader()
    required_headings = {
        "## Dispatch Mode",
        "## Input",
        "## Workflow",
        "## Communication and Artifacts",
        "## Verification Boundary",
        "## Failure and Escalation",
        "## Output Contract",
    }
    for role in _ROLE_DIRECTORIES:
        contract = loader.load(role)
        assert contract.format_version == "mmat-role-card-v1"
        assert contract.fields["format"] == "mmat-role-card-v1"
        assert required_headings <= set(contract.body.splitlines())
        rendered = loader.system_prompt(role)
        assert "Prompt 格式：mmat-role-card-v1" in rendered


def test_all_legacy_and_v3_skills_use_complete_method_cards():
    registry = SkillRegistry()
    assert len(registry.names()) == 95
    for name in registry.names():
        skill = registry.definition(name)
        assert skill.format_version == MECHMATH_SKILL_FORMAT
        assert set(COMMON_METHOD_CARD_SECTIONS) <= set(skill.sections)
        assert skill.source_path.read_text(encoding="utf-8").split("\n")[:8].count(
            "format: mmat-method-card-v1"
        ) == 1


def test_production_projection_exposes_protocol_then_role_math_sections():
    problem = ProblemIR(
        raw_problem="Find the minimum of x^2-4x+1.",
        normalized_problem="Find the minimum of x^2-4x+1.",
        problem_type="calculation",
        answer_type="expression",
        subject_candidates=[("algebra", 0.95)],
        target_phrase="minimum",
        target_kind="optimize",
    )
    composition = DynamicSkillSelector(SkillRegistry(), top_k=2).compose_for_role(
        problem,
        role="PrimarySolver",
        route_skill_names=["quadratic-completion"],
        max_chars=6000,
    )
    assert composition.included
    assert composition.included[0].name == "quadratic-completion"
    assert "格式：mmat-method-card-v1" in composition.text
    assert "## Quick Dispatch" in composition.text
    assert "## Input Contract" in composition.text
    assert "## Workflow" in composition.text
    assert "## Verification Boundary" in composition.text
    assert "## Exact Preconditions" in composition.text
    assert all(item.format_version == "mmat-method-card-v1" for item in composition.included)


def test_compact_v2_projection_keeps_multiple_route_cards_within_budget():
    problem = ProblemIR(
        raw_problem="Compute a numerical matrix expression.",
        normalized_problem="Compute a numerical matrix expression.",
        problem_type="calculation",
        answer_type="expression",
        subject_candidates=[("linear-algebra", 0.95)],
        target_phrase="matrix",
        target_kind="compute_value",
    )
    composition = DynamicSkillSelector(SkillRegistry(), top_k=3).compose_for_role(
        problem,
        role="AlternativeSolver",
        route_skill_names=[
            "linear-algebra",
            "answer-normalization",
            "symbolic-equivalence",
        ],
        max_chars=6000,
    )
    assert len(composition.text) <= 6000
    assert {item.name for item in composition.included} >= {
        "linear-algebra",
        "answer-normalization",
        "symbolic-equivalence",
    }
