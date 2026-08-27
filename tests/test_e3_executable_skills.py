from __future__ import annotations

from types import SimpleNamespace

from mathforge.harness.schemas import EvidenceRecord
from mathforge.skills.evaluation import (
    SkillBenchmarkCase,
    evaluate_skill_specific_benchmark,
)
from mathforge.skills.execution_plan import SkillExecutionPlan, skill_utility
from mathforge.skills.registry import SkillRegistry
from mathforge.skills.runtime import SkillRuntime
from mathforge.skills.selector import DynamicSkillSelector
from mathforge.tools.registry import ToolRegistry


_SECTION_NAMES = (
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


def _skill(name: str, *, requires=(), hooks=(), alternatives=(), signals=()):
    sections = {section: f"{name}:{section}" for section in _SECTION_NAMES}
    return SimpleNamespace(
        name=name,
        version="3.0",
        domain="algebra",
        roles=("PrimarySolver", "VerifierSkeptic"),
        requires=tuple(requires),
        verification_hooks=tuple(hooks),
        alternative_skills=tuple(alternatives),
        failure_signals=tuple(signals),
        sections=sections,
        body="\n".join(sections.values()),
        expected_gain=0.2,
        historical_precision=0.8,
        token_cost=10,
        problem_patterns=(name,),
        triggers=(),
    )


class _Registry:
    def __init__(self, definitions):
        self._definitions = definitions

    def names(self):
        return sorted(self._definitions)

    def definition(self, name):
        return self._definitions[name]


def test_execution_plan_has_required_contract_and_utility():
    plan = SkillExecutionPlan(
        "quadratic-completion",
        "3.0",
        "PrimarySolver",
        40.0,
        ("route_seed",),
        ("a != 0",),
        ("symbolic_equivalence",),
        ("symbolic_equivalence",),
        ("polynomial-factorization",),
        ("verification_failed",),
        ("stop when the leading coefficient is zero",),
        10,
        expected_gain=0.5,
        capability_available=True,
        historical_precision=0.8,
    )
    assert plan.expected_accuracy_gain == 0.4
    assert plan.utility == skill_utility(0.5, 10, historical_precision=0.8)
    assert plan.to_dict()["admitted"] is True


def test_capability_admission_tries_alternative_and_never_injects_missing_tool():
    primary = _skill(
        "primary",
        requires=("missing_tool",),
        hooks=("missing_tool",),
        alternatives=("alternative",),
        signals=("non-strict-boundary-inequality",),
    )
    alternative = _skill("alternative")
    runtime = SkillRuntime(_Registry({"primary": primary, "alternative": alternative}), ToolRegistry())

    plan = runtime.execution_plan("primary", role="PrimarySolver", allow_degraded=False)
    assert plan.admission_status == "alternative"
    assert plan.skill_name == "alternative"
    assert plan.source_skill_name == "primary"
    assert runtime.execution_plan("primary", role="PrimarySolver", allow_degraded=True).admission_status == "alternative"

    outcome = runtime.resolve_failure("primary", ["non-strict-boundary-inequality"])
    assert outcome.status == "fallback"
    assert outcome.alternative_skill == "alternative"
    assert outcome.replan_required is True


def test_hook_tasks_are_bound_to_real_evidence_or_marked_incomplete():
    skill = _skill("density", requires=("density_normalization",), hooks=("density_normalization",))
    runtime = SkillRuntime(_Registry({"density": skill}), ToolRegistry())
    tasks = runtime.hook_tasks(["density"], dependencies=("solve:primary",))
    assert len(tasks) == 1
    assert tasks[0].dependencies == ("solve:primary",)

    record = EvidenceRecord(
        evidence_id="ev-density",
        candidate_id="candidate-1",
        claim_id="claim-1",
        evidence_type="tool:density_normalization",
        status="pass",
        strength="hard",
        description="normalization passed",
        capability="probability_normalization",
        invocation={"tool_name": "density_normalization"},
    )
    consumed = runtime.consume_hook_evidence(tasks, [record])
    assert consumed[0].status == "completed"
    assert consumed[0].evidence_ids == ("ev-density",)


def test_registry_quality_gate_and_role_projection_are_observable():
    registry = SkillRegistry()
    assert registry.quality_report.passed
    assert registry.quality_report.coverage_ready
    assert "alternative strategy" in registry.definition("quadratic-completion").sections


def test_skill_specific_benchmark_requires_taxonomy_and_recommends_downweight_without_gain():
    cases = [
        SkillBenchmarkCase(f"case-{case_type}", "demo", case_type)
        for case_type in ("positive", "negative", "adversarial", "selection", "ablation")
    ]
    records = []
    for case in cases:
        records.extend(
            [
                {"case_id": case.case_id, "skill_enabled": True, "actual": "1", "expected_answer": "1", "answer_type": "integer", "tokens": 10},
                {"case_id": case.case_id, "skill_enabled": False, "actual": "1", "expected_answer": "1", "answer_type": "integer", "tokens": 0},
            ]
        )
    report = evaluate_skill_specific_benchmark(cases, records)
    assert report.complete
    assert report.ablation.tokens_added == 50
    assert report.recommended_action == "downweight_or_disable"
