from __future__ import annotations

from pathlib import Path

from mathforge.agents.registry import PromptContractLoader, SkillRegistry
from mathforge.agents.router_planner import RouterPlanner
from mathforge.parsing.problem_parser import ProblemParser


def test_rule_router_classifies_clear_problem_without_llm():
    calls = 0

    def consume():
        nonlocal calls
        calls += 1

    parsed = ProblemParser().parse("计算矩阵的特征值")
    plan = RouterPlanner().plan(parsed, llm_chat=lambda **_: "{}", consume_call=consume)
    assert plan.primary_subject == "linear-algebra"
    assert calls == 0


def test_ambiguous_router_failure_degrades_to_general_math():
    parsed = ProblemParser().parse("求解这个问题")
    plan = RouterPlanner().plan(
        parsed,
        llm_chat=lambda **_: "not json",
        consume_call=lambda: None,
    )
    assert plan.primary_subject == "general-math"
    assert len([name for name in plan.selected_skills if name not in {"answer-normalization"}]) <= 2


def test_all_domain_skills_load_and_budget_is_enforced():
    registry = SkillRegistry()
    domain_names = [
        path.stem
        for path in (Path(__file__).resolve().parents[1] / "skills" / "domains").glob("*.md")
    ]
    assert len(domain_names) == 18
    assert set(domain_names) <= set(registry.names())
    assert len(registry.compose(registry.names(), 120)) <= 120


def test_all_prompt_contracts_are_statically_valid():
    loader = PromptContractLoader()
    for role in (
        "router_planner",
        "primary_solver",
        "alternative_solver",
        "lemma_curator",
        "verifier_skeptic",
        "repair",
        "finalizer",
    ):
        assert loader.load(role).body
