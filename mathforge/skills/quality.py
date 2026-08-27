"""Content quality gates for executable V3 micro-Skills."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from mathforge.skills.schema import V3_REQUIRED_SECTIONS


QUALITY_GATE_SCHEMA_VERSION = "1.0"
_COUNTEREXAMPLE_NAMES = ("counterexample patterns", "counterexample")


@dataclass(frozen=True)
class SkillQualityReport:
    checked_count: int
    method_count: int
    high_value_count: int
    minimum_high_value_count: int
    failures: tuple[dict[str, Any], ...] = ()
    schema_version: str = QUALITY_GATE_SCHEMA_VERSION

    @property
    def passed(self) -> bool:
        return not self.failures

    @property
    def coverage_ready(self) -> bool:
        return self.high_value_count >= self.minimum_high_value_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "checked_count": self.checked_count,
            "method_count": self.method_count,
            "high_value_count": self.high_value_count,
            "minimum_high_value_count": self.minimum_high_value_count,
            "coverage_ready": self.coverage_ready,
            "passed": self.passed,
            "failures": [dict(item) for item in self.failures],
        }


def validate_skill_content(skill: Any) -> tuple[str, ...]:
    """Return deterministic quality failures for one V3 method package."""

    if str(getattr(skill, "version", "")) != "3.0":
        return ()
    if str(getattr(skill, "kind", "")) != "method":
        return ()
    sections = getattr(skill, "sections", {}) or {}
    failures: list[str] = []
    for section in V3_REQUIRED_SECTIONS:
        aliases = _COUNTEREXAMPLE_NAMES if section == "counterexample patterns" else (section,)
        if not any(str(sections.get(name, "")).strip() for name in aliases):
            failures.append(f"missing:{section}")
    # A section containing only a heading/placeholder is not executable
    # guidance.  Keep the threshold small and deterministic; mathematical
    # correctness belongs to the Skill benchmark, not this content gate.
    for section in V3_REQUIRED_SECTIONS:
        aliases = _COUNTEREXAMPLE_NAMES if section == "counterexample patterns" else (section,)
        content = next((str(sections.get(name, "")).strip() for name in aliases if str(sections.get(name, "")).strip()), "")
        if content and len(content) < 3:
            failures.append(f"too_short:{section}")
    return tuple(dict.fromkeys(failures))


def validate_micro_skill_quality(
    skills: Iterable[Any],
    *,
    minimum_high_value_count: int = 20,
) -> SkillQualityReport:
    """Check the high-value V3 method catalog without model-generated labels."""

    values = list(skills)
    selected = [
        skill
        for skill in values
        if str(getattr(skill, "version", "")) == "3.0"
        and str(getattr(skill, "kind", "")) == "method"
    ]
    failures: list[dict[str, Any]] = []
    for skill in selected:
        for code in validate_skill_content(skill):
            failures.append({"skill_name": str(getattr(skill, "name", "")), "code": code})
    return SkillQualityReport(
        checked_count=len(values),
        method_count=len(selected),
        high_value_count=sum(
            bool(getattr(skill, "roles", ())) and bool(getattr(skill, "problem_patterns", ()))
            for skill in selected
        ),
        minimum_high_value_count=max(1, int(minimum_high_value_count)),
        failures=tuple(failures),
    )


class SkillQualityGate:
    """Reusable fail-closed validator for Skill catalogs."""

    def __init__(self, *, minimum_high_value_count: int = 20) -> None:
        self.minimum_high_value_count = max(1, int(minimum_high_value_count))

    def evaluate(self, skills: Iterable[Any]) -> SkillQualityReport:
        values = list(skills)
        return validate_micro_skill_quality(
            values,
            minimum_high_value_count=self.minimum_high_value_count,
        )

    def assert_valid(self, skills: Iterable[Any]) -> SkillQualityReport:
        report = self.evaluate(skills)
        if not report.passed:
            details = ", ".join(
                f"{item['skill_name']}:{item['code']}" for item in report.failures
            )
            raise ValueError(f"Skill content quality gate failed: {details}")
        return report


__all__ = [
    "QUALITY_GATE_SCHEMA_VERSION",
    "SkillQualityGate",
    "SkillQualityReport",
    "validate_micro_skill_quality",
    "validate_skill_content",
]
