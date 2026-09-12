from __future__ import annotations

from mathforge.skills.schema import SkillPackage


ROLE_SECTIONS = {
    "PrimarySolver": (
        "recognition",
        "do not use when",
        "core theorem",
        "exact preconditions",
        "procedure",
        "branch conditions",
        "failure modes",
        "verification recipe",
        "alternative strategy",
        "stop / escalate conditions",
    ),
    "AlternativeSolver": (
        "recognition",
        "do not use when",
        "exact preconditions",
        "procedure",
        "branch conditions",
        "failure modes",
        "counterexample patterns",
        "verification recipe",
        "alternative strategy",
        "stop / escalate conditions",
    ),
    "LemmaCurator": (
        "core theorem",
        "exact preconditions",
        "procedure",
        "branch conditions",
        "stop / escalate conditions",
    ),
    "VerifierSkeptic": (
        "do not use when",
        "core theorem",
        "exact preconditions",
        "failure modes",
        "counterexample patterns",
        "verification recipe",
        "stop / escalate conditions",
    ),
    "RepairAgent": (
        "do not use when",
        "exact preconditions",
        "procedure",
        "branch conditions",
        "failure modes",
        "verification recipe",
        "alternative strategy",
        "stop / escalate conditions",
    ),
    "LLMFinalizer": (),
}


def project(package: SkillPackage, role: str) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    wanted = ROLE_SECTIONS.get(role, ())
    selected = tuple(name for name in wanted if package.sections.get(name))
    omitted = tuple(name for name in package.sections if name not in selected)
    if not selected:
        return "", selected, omitted
    blocks = [f"# Skill: {package.name} ({package.version})"]
    for name in selected:
        blocks.append(f"## {name.title()}\n{package.sections[name]}")
    return "\n".join(blocks).strip(), selected, omitted
