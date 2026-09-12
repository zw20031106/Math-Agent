from __future__ import annotations

from types import SimpleNamespace

from mathforge.agents.registry import PromptContractLoader
from mathforge.skills.projection import ROLE_SECTIONS, project


def test_phase_p1_prompt_contracts_state_role_specific_math_boundaries():
    loader = PromptContractLoader()
    bodies = {
        role: loader.load(role).body
        for role in (
            "router_planner",
            "primary_solver",
            "alternative_solver",
            "lemma_curator",
            "verifier_skeptic",
            "repair",
            "finalizer",
        )
    }

    assert "RouterIntentV1" in bodies["router_planner"]
    assert "风险判定遵循保守标准" in bodies["router_planner"]
    assert "不要解决题目" in bodies["router_planner"]

    assert "逐项核对精确前提" in bodies["primary_solver"]
    assert "等价、由前推出后" in bodies["primary_solver"]
    assert "存在性、唯一性和充分必要条件" in bodies["primary_solver"]
    assert "不得引入原题没有的假设" in bodies["primary_solver"]

    assert "真实的方法独立性" in bodies["alternative_solver"]
    assert "仅换符号、换推导顺序" in bodies["alternative_solver"]
    assert "缺失条件并 abstain" in bodies["alternative_solver"]

    assert "当前 Proof Obligation" in bodies["lemma_curator"]
    assert "引入原题没有的新假设" in bodies["lemma_curator"]
    assert "未验证引理当作事实" in bodies["lemma_curator"]

    assert "按依赖顺序审计" in bodies["verifier_skeptic"]
    assert "Unknown 永远不等于 pass" in bodies["verifier_skeptic"]
    assert "global_method_failure" in bodies["verifier_skeptic"]

    assert "dependency closure" in bodies["repair"]
    assert "重写无关 Claim" in bodies["repair"]
    assert "重新验证" in bodies["repair"]

    assert "只规范化已选且通过验证的候选" in bodies["finalizer"]
    assert "不得新增推导" in bodies["finalizer"]
    assert "改变任何验证状态" in bodies["finalizer"]


def test_phase_p2_role_projection_matches_mathforge_plan():
    expected = {
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

    assert ROLE_SECTIONS == expected
    assert "exact preconditions" in ROLE_SECTIONS["AlternativeSolver"]
    assert "core theorem" in ROLE_SECTIONS["VerifierSkeptic"]
    assert ROLE_SECTIONS["LLMFinalizer"] == ()

    package = SimpleNamespace(
        name="demo",
        version="3.0",
        sections={"core theorem": "theorem"},
    )
    text, selected, omitted = project(package, "LLMFinalizer")
    assert text == ""
    assert selected == ()
    assert omitted == ("core theorem",)
