from __future__ import annotations

from mathforge.skills.hook_audit import audit_skill_hooks
from mathforge.skills.registry import SkillRegistry
from mathforge.tools.registry import ToolRegistry


_P0 = (
    "dominated-convergence",
    "uniform-convergence",
    "lhopital-limit",
    "epsilon-delta",
    "taylor-remainder",
    "branch-cut-integral",
    "argument-principle",
    "rouche-zero-count",
    "residue-theorem",
    "jordan-form",
    "spectral-theorem",
    "eigenvalue-diagonalization",
    "conditional-expectation",
)


def test_p0_packages_have_explicit_metadata_and_theorem_boundaries():
    registry = SkillRegistry()

    for name in _P0:
        skill = registry.definition(name)
        assert skill.version == "3.0"
        assert skill.description
        assert skill.negative_triggers
        assert skill.required_observables
        assert "numerical" in skill.sections["verification recipe"].casefold() or (
            "symbolic" in skill.sections["verification recipe"].casefold()
            or "matrix_shape_check" in skill.sections["verification recipe"]
            or "density_normalization" in skill.sections["verification recipe"]
        )
        assert len(skill.sections["exact preconditions"]) >= 80
        assert len(skill.sections["failure modes"]) >= 60


def test_weak_p0_hooks_are_described_as_support_not_universal_proof():
    registry = SkillRegistry()
    for name in (
        "dominated-convergence",
        "uniform-convergence",
        "taylor-remainder",
        "branch-cut-integral",
        "argument-principle",
        "rouche-zero-count",
        "jordan-form",
        "spectral-theorem",
        "conditional-expectation",
    ):
        recipe = registry.definition(name).sections["verification recipe"].casefold()
        assert any(
            marker in recipe
            for marker in (
                "only supporting",
                "only as",
                "cannot",
                "not a",
                "does not",
            )
        )


def test_p0_rewrite_reduces_undeclared_recipe_boundaries_without_mapping_errors():
    report = audit_skill_hooks(SkillRegistry(), ToolRegistry())

    assert report.passed
    assert not report.errors
    assert len(report.warnings) == 28
    assert not any(
        item.skill_name in _P0 and item.code == "recipe_strength_undeclared"
        for item in report.warnings
    )

