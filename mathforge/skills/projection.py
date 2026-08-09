from __future__ import annotations

from mathforge.skills.schema import SkillPackage


ROLE_SECTIONS = {
    "PrimarySolver": ("recognition", "core theorem", "exact preconditions", "procedure", "branch conditions"),
    "AlternativeSolver": ("recognition", "procedure", "branch conditions", "alternative strategy", "counterexample patterns"),
    "LemmaCurator": ("core theorem", "exact preconditions", "procedure", "stop / escalate conditions"),
    "VerifierSkeptic": ("do not use when", "exact preconditions", "failure modes", "counterexample patterns", "verification recipe"),
    "RepairAgent": ("exact preconditions", "procedure", "failure modes", "verification recipe", "alternative strategy"),
    "LLMFinalizer": ("verification recipe", "stop / escalate conditions"),
}


def project(package: SkillPackage, role: str) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    wanted = ROLE_SECTIONS.get(role, ())
    selected = tuple(name for name in wanted if package.sections.get(name))
    omitted = tuple(name for name in package.sections if name not in selected)
    blocks = [f"# Skill: {package.name} ({package.version})"]
    for name in selected:
        blocks.append(f"## {name.title()}\n{package.sections[name]}")
    return "\n".join(blocks).strip(), selected, omitted
