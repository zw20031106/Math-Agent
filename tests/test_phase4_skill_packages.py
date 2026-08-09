from __future__ import annotations

from pathlib import Path

import pytest

from mathforge.harness.schemas import ProblemIR
from mathforge.skills.evaluation import evaluate_contract_canary
from mathforge.skills.loader import load_v3_package
from mathforge.skills.registry import SkillRegistry
from mathforge.skills.runtime import SkillRuntime
from mathforge.skills.schema import V3_REQUIRED_SECTIONS
from mathforge.skills.selector import DynamicSkillSelector
from mathforge.tools.registry import ToolRegistry


def _problem(text: str, subject: str, target_kind: str = "compute_value") -> ProblemIR:
    return ProblemIR(
        raw_problem=text,
        normalized_problem=text,
        problem_type="calculation",
        answer_type="expression",
        subject_candidates=[(subject, 0.93)],
        target_phrase=text,
        target_kind=target_kind,
    )


def test_v3_catalog_has_high_frequency_scale_and_complete_packages():
    registry = SkillRegistry()
    v3 = [registry.definition(name) for name in registry.names() if registry.definition(name).version == "3.0"]

    assert 50 <= len(v3) <= 80
    assert all(skill.kind == "method" for skill in v3)
    assert all(set(V3_REQUIRED_SECTIONS) <= set(skill.sections) for skill in v3)
    assert any(registry.definition(name).legacy for name in registry.names())


def test_selector_fixes_tuple_subject_and_projects_top_k_by_pattern():
    selector = DynamicSkillSelector(SkillRegistry(), top_k=2)
    composition = selector.compose_for_role(
        _problem("Find the minimum of the quadratic by completing the square.", "algebra", "optimize"),
        role="PrimarySolver",
        route_skill_names=[],
        max_chars=6000,
    )

    assert composition.included
    assert composition.included[0].name == "quadratic-completion"
    assert "problem_subject" in composition.included[0].reasons
    assert "pattern:" in " ".join(composition.included[0].reasons)
    assert len(
        [
            item
            for item in composition.included
            if item.version == "3.0"
        ]
    ) <= 2
    assert all("Mini Example" not in composition.text for _ in [0])
    assert any("top_k" in item.reasons for item in composition.omitted if item.score > 0)


def test_progressive_reference_is_bounded_and_cannot_escape_package():
    registry = SkillRegistry()
    runtime = SkillRuntime(registry, ToolRegistry())
    fragment = runtime.disclose_reference(
        "rouche-zero-count",
        "references/boundary_check.md",
        max_chars=40,
    )

    assert len(fragment.text) == 40
    assert fragment.truncated is True
    with pytest.raises(ValueError, match="escapes"):
        runtime.disclose_reference("rouche-zero-count", "../../schema.py", max_chars=100)


def test_skill_capabilities_are_only_tool_registry_authorizations():
    registry = SkillRegistry()
    runtime = SkillRuntime(registry, ToolRegistry())
    package = load_v3_package(
        Path(__file__).parents[1]
        / "mathforge"
        / "skills"
        / "packages"
        / "complex_analysis"
        / "rouche-zero-count"
    )
    capabilities = runtime.capabilities(package.name)

    assert capabilities.requested == ("numerical_residual",)
    assert capabilities.authorized == ("numerical_residual",)
    assert capabilities.unavailable == ()


def test_skill_gate_reports_selection_tokens_and_scoped_on_off_ablation():
    report = evaluate_contract_canary(
        [
            {
                "selected": ["quadratic-completion"],
                "expected": ["quadratic-completion"],
                "skill_on_correct": True,
                "skill_off_correct": False,
                "tokens_added": 312,
            },
            {
                "selected": ["rouche-zero-count"],
                "expected": ["rouche-zero-count"],
                "skill_on_correct": True,
                "skill_off_correct": True,
                "tokens_added": 388,
            },
        ]
    )

    assert report.evidence_scope == "synthetic_contract_canary"
    assert report.selection_precision == 1.0
    assert report.selection_recall == 1.0
    assert report.skill_on_accuracy == 1.0
    assert report.skill_off_accuracy == 0.5
    assert report.accuracy_delta == 0.5
    assert report.tokens_added == 700
