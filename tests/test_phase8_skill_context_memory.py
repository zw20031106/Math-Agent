from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from mathforge.context.errors import ContextBudgetExceeded
from mathforge.context.role_views import RoleContextFactory
from mathforge.memory.blackboard import MemoryBlackboard
from mathforge.memory.session_memory import SessionMemory
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.skills.evaluation import evaluate_paired_skill_runs
from mathforge.skills.registry import SkillRegistry
from mathforge.skills.runtime import SkillRuntime
from mathforge.skills.selector import DynamicSkillSelector
from mathforge.tools.registry import ToolRegistry


def test_skill_runtime_builds_capability_hook_plan_and_alternative_branch():
    registry = SkillRegistry()
    runtime = SkillRuntime(registry, ToolRegistry())
    plan = runtime.check_plan("rouche-zero-count")
    assert plan.admitted
    assert plan.required_capabilities == ("numerical_residual",)
    assert plan.verification_hooks == ("numerical_residual",)
    assert plan.selected_tools == ("numerical_residual",)
    assert "argument-principle" in runtime.alternative_skill_names(
        ["rouche-zero-count"]
    )


def test_selector_rejects_missing_capability_before_disclosure():
    definition = SimpleNamespace(
        name="blocked",
        version="3.0",
        domain="algebra",
        roles=("PrimarySolver",),
        problem_patterns=("blocked",),
        triggers=(),
        requires=("missing_tool",),
        verification_hooks=("missing_tool",),
        failure_signals=(),
        sections={
            "recognition": "blocked",
            "do not use when": "never",
            "core theorem": "none",
            "exact preconditions": "none",
            "procedure": "none",
            "branch conditions": "none",
            "failure modes": "none",
            "counterexample patterns": "none",
            "verification recipe": "none",
            "mini example": "none",
            "alternative strategy": "none",
            "stop / escalate conditions": "none",
        },
    )

    class Registry:
        def names(self):
            return ["blocked"]

        def definition(self, name):
            assert name == "blocked"
            return definition

    runtime = SkillRuntime(Registry(), ToolRegistry())
    problem = ProblemParser().parse("blocked algebra problem")
    composition = DynamicSkillSelector(Registry(), runtime=runtime).compose_for_role(
        problem,
        role="PrimarySolver",
        route_skill_names=["blocked"],
        max_chars=2000,
    )
    assert not composition.included
    assert composition.omitted[0].admission_status == "rejected"


def test_reference_disclosure_records_content_hash():
    registry = SkillRegistry()
    runtime = SkillRuntime(registry, ToolRegistry())
    fragment = runtime.disclose_reference(
        "rouche-zero-count",
        "references/boundary_check.md",
        max_chars=100,
    )
    source = (
        Path("mathforge")
        / "skills"
        / "packages"
        / "complex_analysis"
        / "rouche-zero-count"
        / "references"
        / "boundary_check.md"
    )
    assert fragment.sha256 == sha256(source.read_bytes()).hexdigest()


def test_context_records_token_and_core_budgets():
    problem = ProblemParser().parse("Prove that x equals x")
    board = MemoryBlackboard(SessionMemory())
    view = RoleContextFactory().build(
        problem=problem,
        candidates=[],
        evidence=[],
        obligations={},
        blackboard=board,
        role="PrimarySolver",
        max_chars=4000,
        max_tokens=4000,
        core_token_budget=3000,
    )
    assert view.token_count > 0
    assert view.token_count <= view.token_budget
    assert view.core_token_count <= view.core_token_budget
    assert view.payload["metadata"]["token_count"] == view.token_count

    with pytest.raises(ContextBudgetExceeded):
        RoleContextFactory().build(
            problem=problem,
            candidates=[],
            evidence=[],
            obligations={},
            blackboard=board,
            role="PrimarySolver",
            max_chars=4000,
            max_tokens=1,
            core_token_budget=1,
        )


def test_host_summary_is_public_hashable_and_permissioned():
    board = MemoryBlackboard(SessionMemory())
    item = board.publish_host_summary(
        "route_plan",
        {"plan_id": "plan-1", "selected_tools": ["answer_type_check"]},
    )
    assert item.writer == "Host"
    assert item.payload["summary_hash"]
    assert board.view("AlternativeSolver")[0]["category"] == "summary"
    with pytest.raises(PermissionError):
        board.publish("PrimarySolver", "summary", {"x": 1})
    with pytest.raises(ValueError):
        board.publish_host_summary("bad", {"solution_text": "private"})


def test_paired_evaluation_derives_ci_and_failure_strata():
    report = evaluate_paired_skill_runs(
        [
            {"case_id": "a", "skill_enabled": True, "actual": "2", "expected_answer": "2", "answer_type": "integer"},
            {"case_id": "a", "skill_enabled": False, "actual": "1", "expected_answer": "2", "answer_type": "integer"},
            {"case_id": "b", "skill_enabled": True, "actual": "3", "expected_answer": "3", "answer_type": "integer"},
            {"case_id": "b", "skill_enabled": False, "actual": "3", "expected_answer": "3", "answer_type": "integer"},
        ]
    )
    assert report.pair_count == 2
    assert report.on_scored_count == report.off_scored_count == 2
    assert report.failure_strata["skill_off"]["integer_mismatch"] == 1
    assert report.on_ci95[0] <= report.skill_on_accuracy <= report.on_ci95[1]
    with pytest.raises(ValueError, match="manual skill_on_correct"):
        evaluate_paired_skill_runs(
            [{"case_id": "a", "skill_enabled": True, "skill_on_correct": True}]
        )
