"""Deterministic audit of Skill verification hooks.

Skill frontmatter names tools, but a tool name alone is not a mathematical
guarantee.  This module keeps the relationship between a hook, its declared
capability, and the strongest conclusion that capability may support in one
auditable table.  Warnings describe content that needs a Skill rewrite; only
unknown tools and registry contract mismatches block admission.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from mathforge.tools.registry import ToolRegistry
from mathforge.verification.capabilities import (
    ClaimVerificationState,
    VerificationCapability,
)


HOOK_AUDIT_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class HookPolicy:
    """The maximum claim scope exposed by one verification hook."""

    hook: str
    capability: str
    claim_state: str
    claim_scope: str
    maximum_strength: str
    recipe_markers: tuple[str, ...]
    limitation_markers: tuple[str, ...]


# Keep this mapping explicit rather than inferring strength from a tool name.
# In particular, a numerically passing hook remains sampled support and never
# becomes a universal proof merely because a Skill calls it a verifier.
HOOK_POLICIES: dict[str, HookPolicy] = {
    "deterministic_shadow_probe": HookPolicy(
        "deterministic_shadow_probe",
        VerificationCapability.EQUALITY_SYMBOLIC_UNDER_DOMAIN.value,
        ClaimVerificationState.SEMANTICALLY_VERIFIED.value,
        "allowlisted_exact_shape",
        "hard",
        ("exact", "allowlist", "shape"),
        ("unknown", "never"),
    ),
    "safe_parse_expression": HookPolicy(
        "safe_parse_expression",
        VerificationCapability.SYNTAX_RESTRICTED_PARSE.value,
        ClaimVerificationState.SYNTAX_CHECKED.value,
        "syntax_only",
        "hard",
        ("syntax", "parse", "grammar"),
        ("does not prove", "syntax"),
    ),
    "symbolic_equivalence": HookPolicy(
        "symbolic_equivalence",
        VerificationCapability.EQUALITY_SYMBOLIC_UNDER_DOMAIN.value,
        ClaimVerificationState.SEMANTICALLY_VERIFIED.value,
        "conditional_domain_bounded_equality",
        "hard",
        ("domain", "assumption", "condition", "compare", "equivalent"),
        ("assumption", "domain", "unknown"),
    ),
    "simplify_expression": HookPolicy(
        "simplify_expression",
        VerificationCapability.ALGEBRA_SIMPLIFICATION.value,
        ClaimVerificationState.UNKNOWN.value,
        "algebraic_simplification_only",
        "hard",
        ("simplif", "expand", "algebra"),
        ("does not establish", "condition", "theorem"),
    ),
    "numerical_residual": HookPolicy(
        "numerical_residual",
        VerificationCapability.EQUALITY_NUMERICAL_SAMPLES.value,
        ClaimVerificationState.NUMERICALLY_SUPPORTED.value,
        "finite_samples_only",
        "medium",
        ("sample", "finite", "residual", "support", "diagnostic", "cannot"),
        ("cannot prove", "universal", "sample"),
    ),
    "matrix_shape_check": HookPolicy(
        "matrix_shape_check",
        VerificationCapability.MATRIX_SHAPE.value,
        ClaimVerificationState.SEMANTICALLY_VERIFIED.value,
        "matrix_shape_only",
        "hard",
        ("shape", "dimension", "rectangular", "matrix"),
        ("does not prove", "identity", "invertib"),
    ),
    "density_normalization": HookPolicy(
        "density_normalization",
        VerificationCapability.PROBABILITY_NORMALIZATION.value,
        ClaimVerificationState.SEMANTICALLY_VERIFIED.value,
        "normalization_only",
        "hard",
        ("normaliz", "integral", "density", "nonnegative"),
        ("does not prove", "nonnegativity", "density"),
    ),
    "small_case_enumeration": HookPolicy(
        "small_case_enumeration",
        VerificationCapability.FINITE_CASE_EXACT.value,
        ClaimVerificationState.SEMANTICALLY_VERIFIED.value,
        "supplied_finite_cases_only",
        "hard",
        ("finite", "case", "enumerat", "range", "universal"),
        ("cannot prove", "untested", "universal"),
    ),
    "latex_syntax_check": HookPolicy(
        "latex_syntax_check",
        VerificationCapability.SYNTAX_LATEX_BRACE_BALANCE.value,
        ClaimVerificationState.SYNTAX_CHECKED.value,
        "latex_syntax_only",
        "hard",
        ("latex", "syntax", "brace"),
        ("does not validate", "meaning", "syntax"),
    ),
    "answer_type_check": HookPolicy(
        "answer_type_check",
        VerificationCapability.ANSWER_SHAPE.value,
        ClaimVerificationState.UNKNOWN.value,
        "answer_shape_only",
        "hard",
        ("answer", "shape", "type"),
        ("does not prove", "correctness", "shape"),
    ),
}


@dataclass(frozen=True)
class HookAuditFinding:
    skill_name: str
    hook: str
    code: str
    severity: str
    message: str
    expected_capability: str = ""
    actual_capability: str = ""
    expected_claim_state: str = ""
    actual_claim_state: str = ""
    claim_scope: str = ""

    def __post_init__(self) -> None:
        if self.severity not in {"error", "warning"}:
            raise ValueError("HookAuditFinding severity must be error or warning")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HookAuditReport:
    checked_count: int
    findings: tuple[HookAuditFinding, ...] = ()
    schema_version: str = HOOK_AUDIT_SCHEMA_VERSION

    @property
    def errors(self) -> tuple[HookAuditFinding, ...]:
        return tuple(item for item in self.findings if item.severity == "error")

    @property
    def warnings(self) -> tuple[HookAuditFinding, ...]:
        return tuple(item for item in self.findings if item.severity == "warning")

    @property
    def passed(self) -> bool:
        return not self.errors

    def for_skill(self, skill_name: str) -> tuple[HookAuditFinding, ...]:
        return tuple(
            item for item in self.findings if item.skill_name == str(skill_name)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "checked_count": self.checked_count,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "passed": self.passed,
            "findings": [item.to_dict() for item in self.findings],
        }


def hook_policy(hook: str) -> HookPolicy | None:
    """Return the immutable policy for a known hook, if one exists."""

    return HOOK_POLICIES.get(str(hook).strip())


def audit_skill_hooks(
    skills: Iterable[Any] | Any,
    tools: ToolRegistry | None = None,
) -> HookAuditReport:
    """Audit V3 ``requires`` and ``verification_hooks`` against ToolRegistry.

    ``requires`` may contain tools needed while constructing a solution and
    therefore need not equal ``verification_hooks``.  Every field is checked
    independently.  A hook that is known but weak (for example numerical
    sampling) is admitted with an explicit scope warning; it cannot create a
    semantic claim by itself because the evidence layer still gates claims by
    capability and claim kind.
    """

    registry = tools or ToolRegistry()
    definitions = _skill_definitions(skills)
    known = set(registry.names())
    findings: list[HookAuditFinding] = []
    checked = 0
    for definition in definitions:
        if str(getattr(definition, "version", "")) != "3.0":
            continue
        checked += 1
        skill_name = str(getattr(definition, "name", ""))
        required = _text_tuple(getattr(definition, "requires", ()))
        hooks = _text_tuple(getattr(definition, "verification_hooks", ()))
        for name in required:
            if name not in known:
                findings.append(
                    HookAuditFinding(
                        skill_name,
                        name,
                        "unknown_required_capability",
                        "error",
                        "requires names a tool absent from ToolRegistry",
                    )
                )
        required_set = set(required)
        for hook in hooks:
            if hook not in known:
                findings.append(
                    HookAuditFinding(
                        skill_name,
                        hook,
                        "unknown_verification_hook",
                        "error",
                        "verification_hooks names a tool absent from ToolRegistry",
                    )
                )
                continue
            policy = HOOK_POLICIES.get(hook)
            tool = registry.get(hook)
            if policy is None:
                findings.append(
                    HookAuditFinding(
                        skill_name,
                        hook,
                        "unclassified_verification_hook",
                        "error",
                        "known tool has no declared mathematical strength policy",
                    )
                )
                continue
            if hook not in required_set:
                findings.append(
                    HookAuditFinding(
                        skill_name,
                        hook,
                        "hook_not_listed_as_requirement",
                        "warning",
                        "verification hook is not listed in requires; admission and execution may diverge",
                        expected_capability=policy.capability,
                        actual_capability=str(getattr(tool, "capability", "")),
                        claim_scope=policy.claim_scope,
                    )
                )
            actual_capability = str(getattr(tool, "capability", ""))
            actual_claim_state = str(getattr(tool, "claim_state", ""))
            if actual_capability != policy.capability:
                findings.append(
                    HookAuditFinding(
                        skill_name,
                        hook,
                        "tool_capability_mismatch",
                        "error",
                        "ToolRegistry capability disagrees with the hook policy",
                        expected_capability=policy.capability,
                        actual_capability=actual_capability,
                        claim_scope=policy.claim_scope,
                    )
                )
            if actual_claim_state != policy.claim_state:
                findings.append(
                    HookAuditFinding(
                        skill_name,
                        hook,
                        "tool_claim_state_mismatch",
                        "error",
                        "ToolRegistry claim state disagrees with the hook policy",
                        expected_claim_state=policy.claim_state,
                        actual_claim_state=actual_claim_state,
                        claim_scope=policy.claim_scope,
                    )
                )
            if not str(getattr(tool, "proves", "")).strip() or not str(
                getattr(tool, "limitations", "")
            ).strip():
                findings.append(
                    HookAuditFinding(
                        skill_name,
                        hook,
                        "tool_contract_incomplete",
                        "error",
                        "tool must declare both proves and limitations",
                        expected_capability=policy.capability,
                        actual_capability=actual_capability,
                        claim_scope=policy.claim_scope,
                    )
                )
            recipe = _recipe(definition)
            if policy.recipe_markers and not any(
                marker in recipe for marker in policy.recipe_markers
            ):
                findings.append(
                    HookAuditFinding(
                        skill_name,
                        hook,
                        "recipe_strength_undeclared",
                        "warning",
                        "verification recipe does not state the hook's evidence boundary",
                        expected_capability=policy.capability,
                        actual_capability=actual_capability,
                        claim_scope=policy.claim_scope,
                    )
                )
            limitations = str(getattr(tool, "limitations", "")).casefold()
            if policy.limitation_markers and not any(
                marker in limitations for marker in policy.limitation_markers
            ):
                findings.append(
                    HookAuditFinding(
                        skill_name,
                        hook,
                        "tool_limitations_undeclared",
                        "warning",
                        "tool limitations do not repeat the policy boundary",
                        expected_capability=policy.capability,
                        actual_capability=actual_capability,
                        claim_scope=policy.claim_scope,
                    )
                )
    findings.sort(key=lambda item: (item.skill_name, item.hook, item.code))
    return HookAuditReport(checked_count=checked, findings=tuple(findings))


def _skill_definitions(skills: Iterable[Any] | Any) -> tuple[Any, ...]:
    if hasattr(skills, "names") and hasattr(skills, "definition"):
        return tuple(skills.definition(name) for name in skills.names())
    return tuple(skills)


def _text_tuple(values: Iterable[Any] | Any) -> tuple[str, ...]:
    if isinstance(values, str):
        values = (values,)
    return tuple(
        dict.fromkeys(
            str(value).strip()
            for value in (values or ())
            if str(value).strip()
        )
    )


def _recipe(definition: Any) -> str:
    sections = getattr(definition, "sections", {}) or {}
    if isinstance(sections, dict):
        return str(sections.get("verification recipe", "")).casefold()
    return ""


__all__ = [
    "HOOK_AUDIT_SCHEMA_VERSION",
    "HOOK_POLICIES",
    "HookAuditFinding",
    "HookAuditReport",
    "HookPolicy",
    "audit_skill_hooks",
    "hook_policy",
]
