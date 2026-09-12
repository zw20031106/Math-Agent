from __future__ import annotations

from pathlib import Path

from mathforge.harness.schemas import ProblemIR
from mathforge.skills.hook_audit import audit_skill_hooks
from mathforge.skills.registry import SkillRegistry
from mathforge.skills.schema import V3_REQUIRED_SECTIONS
from mathforge.skills.selector import DynamicSkillSelector
from mathforge.tools.registry import ToolRegistry


_EXTERNAL = (
    "strategy-progress-assessment",
    "root-finding",
    "proof-strategy-selection",
    "mathematical-induction",
    "contradiction-contrapositive",
    "existence-uniqueness",
    "case-split-wlog",
    "proof-theory",
    "lean-proof-workflow",
)


def _problem(text: str, subject: str, target_kind: str = "prove") -> ProblemIR:
    return ProblemIR(
        raw_problem=text,
        normalized_problem=text,
        problem_type="proof",
        answer_type="proof",
        subject_candidates=[(subject, 0.95)],
        target_phrase=text,
        target_kind=target_kind,
    )


def test_external_packages_are_complete_v3_rewrites_with_boundaries():
    registry = SkillRegistry()

    for name in _EXTERNAL:
        skill = registry.definition(name)
        assert skill.version == "3.0"
        assert skill.kind == "method"
        assert set(V3_REQUIRED_SECTIONS) <= set(skill.sections)
        assert skill.description
        assert skill.negative_triggers
        assert skill.required_observables
        assert len(skill.sections["exact preconditions"]) >= 80
        assert len(skill.sections["failure modes"]) >= 60
        recipe = skill.sections["verification recipe"].casefold()
        assert any(
            marker in recipe
            for marker in ("support", "cannot", "not a", "does not", "only")
        )


def test_external_rewrites_use_only_current_tools_and_no_runtime_commands():
    registry = SkillRegistry()
    report = audit_skill_hooks(registry, ToolRegistry())

    assert report.passed
    assert not any(
        item.skill_name in _EXTERNAL
        and item.code in {"recipe_strength_undeclared", "unknown_verification_hook"}
        for item in report.findings
    )
    forbidden = (
        "bash",
        "scipy.optimize",
        "z3_solve.py",
        "allowed-tools",
        "read tool",
        "claude-specific",
    )
    for name in _EXTERNAL:
        body = registry.definition(name).body.casefold()
        assert not any(marker in body for marker in forbidden)


def test_positive_negative_and_adversarial_selection_signals_are_declared():
    registry = SkillRegistry()
    selector = DynamicSkillSelector(registry, top_k=3)

    root = selector.compose_for_role(
        _problem("在区间[1,2]上求 x^2-2=0 的数值根并给出误差依据。", "numerical_analysis", "compute_value"),
        role="PrimarySolver",
        route_skill_names=["root-finding"],
        max_chars=6000,
    )
    assert any(item.name == "root-finding" for item in root.included)

    induction = registry.definition("mathematical-induction")
    assert any("finite" in item.casefold() for item in induction.negative_triggers)
    assert "measure decreases" in induction.sections["exact preconditions"]
    assert "cannot prove" in induction.sections["verification recipe"].casefold()

    lean = registry.definition("lean-proof-workflow")
    assert "unsupported" in lean.sections["verification recipe"].casefold()
    assert "checker output" in lean.sections["exact preconditions"].casefold()


def test_source_attribution_records_revisions_licenses_and_transform_controls():
    path = Path(__file__).parents[1] / "mathforge" / "skills" / "packages" / "references" / "source_attribution.md"
    text = path.read_text(encoding="utf-8")

    for value in (
        "Continuous-Claude-v3",
        "Tibsfox/gsd-skill-creator",
        "trailofbits/skills",
        "d07ff4b06b62f43771bc0c927d0211b734d6149e",
        "e179dfe911f3b3c2ff8bcd90ecd6ee4738648d17",
        "321ccfe628eca0d314b0ee4eaffcdd8a05639aaf",
        "MIT License",
        "MariaDB-derived",
        "CC BY-SA 4.0",
        "Bash",
        "ToolRegistry",
    ):
        assert value in text
