from __future__ import annotations

from types import SimpleNamespace

from mathforge.harness.schemas import ProblemIR
from mathforge.skills.loader import load_v3_package
from mathforge.skills.registry import SkillRegistry
from mathforge.skills.selector import DynamicSkillSelector


_SECTIONS = (
    "recognition",
    "do not use when",
    "core theorem",
    "exact preconditions",
    "procedure",
    "branch conditions",
    "failure modes",
    "counterexample patterns",
    "verification recipe",
    "mini example",
    "alternative strategy",
    "stop / escalate conditions",
)


def _package_text(metadata: str = "") -> str:
    body = "\n".join(
        f"## {section.title()}\n{section} content" for section in _SECTIONS
    )
    return f"""---
name: metadata-demo
version: 3.0
domain: calculus
subdomain: limits
kind: method
roles: [PrimarySolver, VerifierSkeptic]
triggers: [limit]
problem_patterns: [limit]
method_family: limit-analysis
alternative_skills: []
requires: numerical_residual
failure_signals: verification_failed
verification_hooks: numerical_residual
{metadata}---
{body}
"""


def test_loader_accepts_optional_v3_metadata_and_yaml_subset(tmp_path):
    source = tmp_path / "SKILL.md"
    source.write_text(
        _package_text(
            """description: >
  Apply limit rules only under the stated domain.
  Keep boundary cases explicit.
negative_triggers:
  - finite sequence
  - no indeterminate form
required_observables: [indeterminate form, denominator nonzero]
"""
        ),
        encoding="utf-8",
    )

    package = load_v3_package(source)

    assert package.description == (
        "Apply limit rules only under the stated domain. Keep boundary cases explicit."
    )
    assert package.negative_triggers == ("finite sequence", "no indeterminate form")
    assert package.required_observables == (
        "indeterminate form",
        "denominator nonzero",
    )


def test_existing_v3_packages_default_optional_metadata_without_schema_bump():
    package = SkillRegistry().definition("quadratic-completion")

    assert package.version == "3.0"
    assert package.description == ""
    assert package.negative_triggers == ()
    assert package.required_observables == ()


def test_selector_uses_metadata_as_bounded_ranking_evidence():
    problem = ProblemIR(
        raw_problem="Evaluate a limit with an indeterminate form; a finite sequence is a distractor.",
        normalized_problem="Evaluate a limit with an indeterminate form; a finite sequence is a distractor.",
        problem_type="calculation",
        answer_type="expression",
        subject_candidates=[("calculus", 0.95)],
        target_phrase="limit",
        target_kind="compute_value",
    )
    definition = SimpleNamespace(
        name="metadata-demo",
        domain="calculus",
        problem_patterns=("limit",),
        triggers=("indeterminate form",),
        failure_signals=(),
        description="limit",
        negative_triggers=("finite sequence",),
        required_observables=("indeterminate form", "derivative sign"),
    )
    context = DynamicSkillSelector._context(problem, None, ())

    score, reasons = DynamicSkillSelector._score(
        definition,
        problem,
        context,
        {"metadata-demo"},
        (),
        None,
    )

    assert score > 0  # metadata refines ranking; it is not a direct veto
    assert "negative_trigger:finite sequence" in reasons
    assert "required_observable:indeterminate form" in reasons
    assert "missing_required_observable:derivative sign" in reasons
    assert "description_match" in reasons
