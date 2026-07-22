from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Callable

from mathforge.harness.schemas import ProblemIR, RoutePlan


_SUBJECT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "algebra": ("方程", "多项式", "inequality", "polynomial", "equation"),
    "geometry": ("三角形", "圆", "几何", "triangle", "circle", "angle"),
    "number-theory": ("素数", "整除", "同余", "prime", "divisib", "modulo"),
    "combinatorics": ("排列", "组合", "计数", "permutation", "combination", "counting"),
    "probability": ("概率", "随机", "probability", "random"),
    "calculus": ("导数", "积分", "极限", "derivative", "integral", "limit"),
    "linear-algebra": ("矩阵", "向量", "特征值", "matrix", "vector", "eigenvalue"),
    "differential-equations": ("微分方程", "differential equation", "ode", "pde"),
    "complex-analysis": ("复变", "留数", "holomorphic", "residue", "complex plane"),
    "real-analysis": ("一致收敛", "测度", "real analysis", "uniform convergence", "measure"),
    "statistics": ("统计", "估计量", "回归", "statistics", "estimator", "regression"),
    "optimization": ("最优化", "最大值", "最小值", "optimization", "maximum", "minimum"),
    "discrete-math": ("图论", "递推", "graph", "recurrence"),
    "logic": ("命题", "谓词", "逻辑", "predicate", "logic"),
    "set-theory": ("集合", "基数", "set theory", "cardinality"),
    "topology": ("拓扑", "紧致", "同胚", "topology", "compact", "homeomorph"),
    "numerical-analysis": ("数值", "误差", "迭代法", "numerical", "rounding error"),
}


class RouterRuleEngine:
    def rank(self, problem: ProblemIR) -> list[tuple[str, float]]:
        lowered = problem.normalized_problem.lower()
        scores: list[tuple[str, float]] = []
        for subject, keywords in _SUBJECT_KEYWORDS.items():
            hits = sum(keyword in lowered for keyword in keywords)
            if hits:
                scores.append((subject, min(0.95, 0.72 + 0.08 * hits)))
        return sorted(scores, key=lambda item: (-item[1], item[0])) or [("general-math", 0.4)]

    def plan(self, problem: ProblemIR) -> RoutePlan:
        ranked = self.rank(problem)
        primary, top_score = ranked[0]
        auxiliary = None
        if len(ranked) > 1 and top_score < 0.75 and top_score - ranked[1][1] < 0.15:
            auxiliary = ranked[1][0]
        risk = "high" if "long_reasoning" in problem.risk_flags else "medium" if top_score < 0.75 else "low"
        candidate_count = {"low": 1, "medium": 2, "high": 3}[risk]
        skills = [primary]
        if auxiliary:
            skills.append(auxiliary)
        skills.extend(["proof-obligation" if problem.problem_type == "proof" else "answer-normalization"])
        tools = ["answer_type_check"]
        if problem.answer_type == "expression":
            tools.append("symbolic_equivalence")
        return RoutePlan(
            primary_subject=primary,
            auxiliary_subject=auxiliary,
            problem_type=problem.problem_type,
            answer_type=problem.answer_type,
            risk_level=risk,
            selected_skills=skills,
            selected_tools=tools,
            candidate_count=candidate_count,
            max_reasoning_rounds=2 if risk == "high" else 1,
            use_rag=risk in {"medium", "high"},
            use_lemma_loop=risk == "high",
            use_llm_finalizer=problem.problem_type in {"proof", "explanation"},
        )


class RouterPlanner:
    def __init__(self, rule_engine: RouterRuleEngine | None = None) -> None:
        self._rules = rule_engine or RouterRuleEngine()

    def plan(
        self,
        problem: ProblemIR,
        *,
        llm_chat: Callable[..., str] | None = None,
        consume_call: Callable[[], None] | None = None,
    ) -> RoutePlan:
        rule_plan = self._rules.plan(problem)
        top_score = self._rules.rank(problem)[0][1]
        if top_score >= 0.75 or llm_chat is None or consume_call is None:
            return rule_plan
        try:
            consume_call()
            response = llm_chat(
                messages=[
                    {"role": "system", "content": "Classify the math domain. Return JSON only."},
                    {
                        "role": "user",
                        "content": (
                            f"Problem:\n{problem.normalized_problem}\n\n"
                            'Return {"primary_subject":"...","auxiliary_subject":null,'
                            '"risk_level":"low|medium|high"}.'
                        ),
                    },
                ],
                temperature=0.0,
                max_tokens=256,
            )
            match = re.search(r"\{.*\}", response, re.DOTALL)
            payload = json.loads(match.group(0)) if match else {}
            primary = str(payload.get("primary_subject", "general-math"))
            if primary not in {*_SUBJECT_KEYWORDS, "general-math"}:
                primary = "general-math"
            auxiliary = payload.get("auxiliary_subject")
            if auxiliary not in _SUBJECT_KEYWORDS or auxiliary == primary:
                auxiliary = None
            risk = str(payload.get("risk_level", rule_plan.risk_level))
            if risk not in {"low", "medium", "high"}:
                risk = rule_plan.risk_level
            selected = [primary] + ([auxiliary] if auxiliary else [])
            selected.append("proof-obligation" if problem.problem_type == "proof" else "answer-normalization")
            return replace(
                rule_plan,
                primary_subject=primary,
                auxiliary_subject=auxiliary,
                risk_level=risk,
                selected_skills=selected,
                candidate_count={"low": 1, "medium": 2, "high": 3}[risk],
            )
        except (ValueError, TypeError, json.JSONDecodeError, RuntimeError):
            return rule_plan
