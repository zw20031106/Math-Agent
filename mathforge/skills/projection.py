from __future__ import annotations

from mathforge.skills.schema import SkillPackage
from mathforge.skills.mechmath_format import (
    COMMON_METHOD_CARD_SECTIONS,
    render_method_card,
)


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
    # The common method-card protocol is rendered for every role, so it is not
    # reported as omitted even though the role-specific tuple remains stable
    # for compatibility with existing admission traces.
    omitted = tuple(
        name
        for name in package.sections
        if name not in selected and name not in COMMON_METHOD_CARD_SECTIONS
    )
    if not selected:
        return "", selected, omitted
    return render_method_card(package, role, selected), selected, omitted
