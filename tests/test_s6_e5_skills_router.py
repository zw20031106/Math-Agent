from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

from mathforge.agents.registry import (
    FIXED_ROLES,
    SKILL_REQUIRED_SECTIONS,
    SkillRegistry,
)
from mathforge.agents.router_planner import (
    RouterPlanner,
    RouterRuleEngine,
    method_families_for,
    selected_skills_for,
)
from mathforge.config import HarnessConfig
from mathforge.evaluation.routing import evaluate_router_gold
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.runtime import MathForgeHarness


ROOT = Path(__file__).resolve().parents[1]

DOMAIN_PROBES = {
    "abstract-algebra": "抽象代数中的群同态",
    "advanced-linear-algebra": "高等代数 Jordan 标准形",
    "advanced-real-analysis": "数学分析中的幂级数收敛区间",
    "algebra": "Solve the polynomial equation.",
    "calculus": "Evaluate an integral using a derivative identity.",
    "combinatorics": "用排列组合完成计数",
    "complex-analysis": "复分析中的留数",
    "differential-equations": "Solve this differential equation.",
    "differential-geometry": "微分几何中的 Gaussian 曲率",
    "discrete-math": "图论递推",
    "functional-analysis": "泛函分析中的算子范数",
    "general-math": "求解这个问题",
    "geometry": "三角形几何",
    "linear-algebra": "Find a matrix eigenvalue.",
    "logic": "命题逻辑",
    "measure-integration": "测度积分与 Lebesgue 积分",
    "number-theory": "素数整除与同余",
    "numerical-analysis": "数值分析中的 Simpson 公式",
    "operations-research": "运筹学中的最大流",
    "optimization": "求这个最优化问题",
    "ordinary-differential-equations": "求解常微分方程初值问题",
    "partial-differential-equations": "求解偏微分方程热方程",
    "probability": "概率论中的随机变量",
    "real-analysis": "Use real analysis and uniform convergence.",
    "regression": "线性回归的最小二乘估计",
    "set-theory": "集合论中的基数",
    "statistics": "统计推断中的最大似然估计量",
    "stochastic-processes": "随机过程中的 Markov 链",
    "topology": "拓扑学中的同调群",
}


class SkillCaptureClient:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    def chat(self, *, messages, temperature, max_tokens):
        del temperature, max_tokens
        self.calls.append(messages)
        method = messages[-1]["content"].split(
            "Required core method family: ",
            1,
        )[1].split(".", 1)[0]
        return json.dumps(
            {
                "method": method,
                "method_steps": [
                    {
                        "step_id": "s1",
                        "kind": "conclusion",
                        "claim_ids": ["c1"],
                        "theorem": "",
                    }
                ],
                "solution_text": "A direct calculation gives the answer.",
                "public_solution_steps": [
                    "Apply the stated matrix relation to obtain the value."
                ],
                "final_answer": "1",
                "assumptions": [],
                "theorems": [],
                "claims": [
                    {
                        "claim_id": "c1",
                        "statement": "The requested value is 1.",
                        "depends_on": [],
                        "check_type": "answer_type_check",
                        "importance": "critical",
                    }
                ],
                "unresolved_obligations": [],
            }
        )


def _skill_runtime_config() -> HarnessConfig:
    return replace(
        HarnessConfig(),
        max_model_calls=1,
        enable_router=True,
        enable_skills=True,
        enable_alternatives=False,
        enable_tools=False,
        enable_evidence=False,
        enable_proof_obligations=False,
        enable_verifier=False,
        enable_memory=False,
        enable_lemma_loop=False,
        enable_rag=False,
        enable_repair=False,
        enable_finalizer=False,
    )


def test_all_35_skills_use_complete_skill_2_contracts():
    registry = SkillRegistry()
    domain_names = [
        name for name in registry.names() if registry.definition(name).kind == "domain"
    ]
    general_names = [
        name for name in registry.names() if registry.definition(name).kind == "general"
    ]

    assert len(domain_names) == 29
    assert len(general_names) == 6
    for name in registry.names():
        definition = registry.definition(name)
        assert definition.version == "2.0"
        assert definition.triggers
        assert definition.roles
        assert set(definition.roles) <= set(FIXED_ROLES)
        assert set(SKILL_REQUIRED_SECTIONS) <= set(definition.sections)


def test_skill_composition_is_atomic_and_role_compatible():
    registry = SkillRegistry()
    name = "advanced-linear-algebra"
    definition = registry.definition(name)
    complete = f"# Skill: {name}\n{definition.body}".strip()

    omitted = registry.compose_for_role(
        [name],
        max_chars=len(complete) - 1,
        role="PrimarySolver",
    )
    included = registry.compose_for_role(
        [name],
        max_chars=len(complete),
        role="PrimarySolver",
    )

    assert omitted.text == ""
    assert omitted.omitted == (name,)
    assert included.text == complete
    assert included.included == (name,)
    assert registry.compose_for_role(
        ["counterexample-search"],
        max_chars=6000,
        role="PrimarySolver",
    ).text == ""
    assert registry.compose_for_role(
        ["counterexample-search"],
        max_chars=6000,
        role="VerifierSkeptic",
    ).included == ("counterexample-search",)


def test_every_domain_skill_is_reachable_and_has_three_method_families():
    registry = SkillRegistry()
    router = RouterRuleEngine()
    parser = ProblemParser()
    domain_names = {
        name for name in registry.names() if registry.definition(name).kind == "domain"
    }

    assert set(DOMAIN_PROBES) == domain_names
    assert set(router.subjects()) == domain_names
    for expected, problem in DOMAIN_PROBES.items():
        assert router.rank(parser.parse(problem))[0][0] == expected
        methods = method_families_for(expected, "calculation")
        assert len(methods) == len(set(methods)) == 3
        assert all(method.strip() for method in methods)


def test_all_six_general_skills_are_selected_and_reach_their_roles():
    registry = SkillRegistry()
    parser = ProblemParser()
    proof = replace(
        parser.parse("Prove by contradiction that a numerical expression is equal."),
        answer_type="expression",
    )
    selected = selected_skills_for(
        proof,
        primary_subject="numerical-analysis",
        auxiliary_subject=None,
        risk_level="high",
    )

    assert {
        "answer-normalization",
        "counterexample-search",
        "lemma-compression",
        "numerical-stability",
        "proof-obligation",
        "symbolic-equivalence",
    } <= set(selected)
    expected_roles = {
        "answer-normalization": "LLMFinalizer",
        "counterexample-search": "VerifierSkeptic",
        "lemma-compression": "LemmaCurator",
        "numerical-stability": "PrimarySolver",
        "proof-obligation": "RepairAgent",
        "symbolic-equivalence": "AlternativeSolver",
    }
    for skill, role in expected_roles.items():
        assert skill in registry.names_for_role(selected, role)
        assert skill in registry.compose_for_role(
            [skill],
            max_chars=6000,
            role=role,
        ).included


def test_low_parser_confidence_and_missing_skill_raise_explicit_risk():
    parser = ProblemParser()
    low_confidence = replace(
        parser.parse("Solve the polynomial equation."),
        parser_confidence=0.2,
    )
    low_plan = RouterRuleEngine().plan(low_confidence)
    general_problem = parser.parse("求解这个问题")
    general_plan = RouterRuleEngine().plan(general_problem)

    assert "low_parser_confidence" in low_plan.complexity_flags
    assert low_plan.risk_level in {"medium", "high"}
    assert "general_math_fallback" in general_plan.complexity_flags
    assert general_plan.risk_level == "medium"
    assert RouterPlanner().routing_reasons(general_problem) == [
        "general-math:no_registered_subject_trigger"
    ]


def test_llm_router_override_has_an_explicit_trace_reason():
    problem = ProblemParser().parse("求解这个问题")
    router = RouterPlanner()
    plan = router.plan(
        problem,
        llm_chat=lambda **_: (
            '{"primary_subject":"topology","risk_level":"medium"}'
        ),
        consume_call=lambda: None,
    )

    assert plan.primary_subject == "topology"
    assert router.routing_reasons(problem, plan)[0] == (
        "llm_router:primary_subject:topology"
    )


def test_reviewed_88_case_router_gold_meets_e5_thresholds_and_beats_baseline():
    result = evaluate_router_gold(ROOT / "data" / "dev_set_2_gold.jsonl")
    baseline = json.loads(
        (ROOT / "data" / "router_e5_baseline.json").read_text(encoding="utf-8")
    )

    assert result.case_count == 88
    assert result.top1_accuracy >= 0.90
    assert result.top2_accuracy >= 0.97
    assert result.general_top1_count == 0
    assert result.top1_hits > baseline["top1_hits"]
    assert result.top2_hits > baseline["top2_hits"]
    assert result.general_top1_count < baseline["general_top1_count"]


def test_runtime_injects_role_skill_blocks_and_records_route_evidence():
    client = SkillCaptureClient()
    result = MathForgeHarness(client, _skill_runtime_config()).solve(
        "计算高等代数矩阵的特征值。",
        {},
    )
    route = next(
        event for event in result["trace"] if event["event"] == "route_planned"
    )
    selected = next(
        event for event in result["trace"] if event["event"] == "skills_selected"
    )
    solver_prompt = client.calls[0][-1]["content"]

    assert result["run_metrics"]["outcome"] == "primary"
    assert route["primary_subject"] == "advanced-linear-algebra"
    assert route["routing_reasons"]
    assert {
        (item["name"], item["role"])
        for item in selected["skills"]
    } >= {
        ("advanced-linear-algebra", "PrimarySolver"),
        ("answer-normalization", "PrimarySolver"),
    }
    assert "# Skill: advanced-linear-algebra" in solver_prompt
    assert "# Skill: answer-normalization" in solver_prompt


def test_runtime_composes_all_six_general_skills_for_compatible_roles():
    proof_result = MathForgeHarness(
        SkillCaptureClient(),
        _skill_runtime_config(),
    ).solve(
        "Prove by contradiction that a numerical expression is equal.",
        {},
    )
    expression_result = MathForgeHarness(
        SkillCaptureClient(),
        _skill_runtime_config(),
    ).solve(
        "Compute a numerical matrix expression.",
        {},
    )
    by_role = {
        (item["name"], item["role"])
        for result in (proof_result, expression_result)
        for event in result["trace"]
        if event["event"] == "skills_selected"
        for item in event["skills"]
    }

    assert {
        ("answer-normalization", "PrimarySolver"),
        ("counterexample-search", "VerifierSkeptic"),
        ("lemma-compression", "LemmaCurator"),
        ("numerical-stability", "PrimarySolver"),
        ("proof-obligation", "RepairAgent"),
        ("symbolic-equivalence", "AlternativeSolver"),
    } <= by_role
