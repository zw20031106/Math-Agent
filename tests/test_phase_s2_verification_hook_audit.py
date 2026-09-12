from __future__ import annotations

from types import SimpleNamespace

from mathforge.skills.hook_audit import audit_skill_hooks, hook_policy
from mathforge.skills.registry import SkillRegistry
from mathforge.skills.runtime import SkillRuntime
from mathforge.tools.registry import ToolDefinition, ToolRegistry
from mathforge.verification.capabilities import ClaimVerificationState


_SECTIONS = {
    "verification recipe": "Check finite samples and report residual support only.",
}


def _skill(
    name: str,
    *,
    requires=("numerical_residual",),
    hooks=("numerical_residual",),
):
    return SimpleNamespace(
        name=name,
        version="3.0",
        requires=tuple(requires),
        verification_hooks=tuple(hooks),
        sections=_SECTIONS,
    )


class _Registry:
    def __init__(self, definitions):
        self._definitions = definitions

    def names(self):
        return sorted(self._definitions)

    def definition(self, name):
        return self._definitions[name]


class _Tools:
    def __init__(self, definition):
        self._definition = definition

    def names(self):
        return [self._definition.name]

    def get(self, name):
        assert name == self._definition.name
        return self._definition


def test_real_v3_catalog_has_no_tool_mapping_errors_and_surfaces_weak_recipes():
    report = audit_skill_hooks(SkillRegistry(), ToolRegistry())

    assert report.checked_count == 51
    assert report.passed
    assert not report.errors
    assert report.warnings
    assert any(
        item.skill_name == "dominated-convergence"
        and item.code == "recipe_strength_undeclared"
        for item in report.warnings
    )
    policy = hook_policy("numerical_residual")
    assert policy is not None
    assert policy.claim_scope == "finite_samples_only"
    assert policy.maximum_strength == "medium"
    assert (
        ToolRegistry().get("numerical_residual").claim_state
        == ClaimVerificationState.NUMERICALLY_SUPPORTED.value
    )


def test_runtime_exposes_audit_scope_without_turning_weak_hook_into_proof():
    runtime = SkillRuntime(SkillRegistry(), ToolRegistry())
    plan = runtime.check_plan("dominated-convergence")

    assert plan.admitted
    assert plan.audit_errors == ()
    assert any(code.startswith("recipe_strength_undeclared:") for code in plan.audit_warnings)
    assert dict(plan.hook_assurance)["numerical_residual"] == "finite_samples_only"
    assert plan.to_dict()["hook_assurance"] == {
        "numerical_residual": "finite_samples_only"
    }
    assert runtime.hook_audit_report.passed


def test_unknown_requirement_and_hook_are_blocking_audit_errors():
    report = audit_skill_hooks(
        [_skill("bad", requires=("missing_tool",), hooks=("missing_hook",))],
        ToolRegistry(),
    )

    assert not report.passed
    assert {item.code for item in report.errors} == {
        "unknown_required_capability",
        "unknown_verification_hook",
    }


def test_capability_and_claim_state_mismatch_blocks_runtime_admission():
    wrong_tool = ToolDefinition(
        "numerical_residual",
        lambda **_: {"status": "pass", "strength": "hard", "summary": "", "payload": {}},
        True,
        "finite samples",
        "cannot prove universal equality",
        capability="matrix.shape",
        claim_state=ClaimVerificationState.SEMANTICALLY_VERIFIED.value,
    )
    skill = _skill("mismatch")
    report = audit_skill_hooks([skill], _Tools(wrong_tool))

    assert not report.passed
    assert {item.code for item in report.errors} == {
        "tool_capability_mismatch",
        "tool_claim_state_mismatch",
    }

    runtime = SkillRuntime(_Registry({"mismatch": skill}), _Tools(wrong_tool))
    plan = runtime.check_plan("mismatch")
    assert not plan.admitted
    assert plan.status == "verification_hook_invalid"
    assert any(code.startswith("tool_capability_mismatch:") for code in plan.audit_errors)


def test_hook_can_be_a_verification_tool_without_being_a_required_solver_tool():
    skill = _skill("support-only", requires=(), hooks=("numerical_residual",))
    report = audit_skill_hooks([skill], ToolRegistry())

    assert report.passed
    assert any(item.code == "hook_not_listed_as_requirement" for item in report.warnings)

