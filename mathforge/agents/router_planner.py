from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from typing import Callable

from mathforge.agents.registry import PromptContractLoader
from mathforge.context.snapshots import RoleContextView
from mathforge.harness.errors import BudgetExceeded
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

_METHOD_FAMILIES: dict[str, tuple[str, str, str]] = {
    "algebra": ("substitution-elimination", "factorization-invariant", "structural-transform"),
    "geometry": ("synthetic-geometry", "coordinate-geometry", "vector-transformation"),
    "number-theory": ("congruence", "valuation-factorization", "descent-extremal"),
    "combinatorics": ("bijection-counting", "recurrence-generating", "invariant-extremal"),
    "probability": ("conditioning", "indicator-linearity", "distribution-transform"),
    "calculus": ("direct-analytic", "change-of-variable", "estimate-limit"),
    "linear-algebra": ("row-space", "spectral", "linear-map-invariant"),
    "optimization": ("calculus-stationarity", "convexity-inequality", "duality-transform"),
    "logic": ("direct-deduction", "contradiction", "model-counterexample"),
    "general-math": ("direct-deduction", "constructive-computation", "contradiction-extremal"),
}


@dataclass(frozen=True)
class RoutePolicy:
    candidate_count: int
    max_reasoning_rounds: int
    use_rag: bool
    use_lemma_loop: bool
    use_llm_finalizer: bool


@dataclass(frozen=True)
class RouteAnalysis:
    subject_candidates: list[tuple[str, float]]
    confidence: float
    ambiguity_margin: float
    complexity_flags: list[str]
    risk_level: str


def derive_route_policy(risk_level: str, problem_type: str) -> RoutePolicy:
    if risk_level not in {"low", "medium", "high"}:
        raise ValueError(f"unsupported risk level: {risk_level}")
    return RoutePolicy(
        candidate_count={"low": 1, "medium": 2, "high": 3}[risk_level],
        max_reasoning_rounds=2 if risk_level == "high" else 1,
        use_rag=risk_level in {"medium", "high"},
        use_lemma_loop=risk_level == "high",
        use_llm_finalizer=problem_type in {"proof", "explanation"},
    )


def method_families_for(subject: str, problem_type: str) -> list[str]:
    families = list(_METHOD_FAMILIES.get(subject, _METHOD_FAMILIES["general-math"]))
    if problem_type == "proof" and "contradiction" not in " ".join(families):
        families[-1] = "contradiction-or-extremal"
    return families


class RouterRuleEngine:
    def rank(self, problem: ProblemIR) -> list[tuple[str, float]]:
        lowered = problem.normalized_problem.lower()
        scores: list[tuple[str, float]] = []
        for subject, keywords in _SUBJECT_KEYWORDS.items():
            hits = sum(keyword in lowered for keyword in keywords)
            if hits:
                scores.append((subject, round(min(0.95, 0.72 + 0.08 * hits), 2)))
        return sorted(scores, key=lambda item: (-item[1], item[0])) or [("general-math", 0.4)]

    def analyze(self, problem: ProblemIR) -> RouteAnalysis:
        ranked = self.rank(problem)
        confidence = ranked[0][1]
        ambiguity_margin = (
            round(confidence - ranked[1][1], 4) if len(ranked) > 1 else 1.0
        )
        complexity_flags = self._complexity_flags(
            problem,
            mixed_domain=len(ranked) > 1 and ambiguity_margin <= 0.12,
        )
        if "long_reasoning" in problem.risk_flags or len(complexity_flags) >= 3:
            risk = "high"
        elif complexity_flags or confidence < 0.75:
            risk = "medium"
        else:
            risk = "low"
        return RouteAnalysis(
            subject_candidates=ranked,
            confidence=confidence,
            ambiguity_margin=ambiguity_margin,
            complexity_flags=complexity_flags,
            risk_level=risk,
        )

    def plan(self, problem: ProblemIR) -> RoutePlan:
        analysis = self.analyze(problem)
        ranked = analysis.subject_candidates
        problem.subject_candidates = list(ranked)
        problem.validate()
        primary, top_score = ranked[0]
        auxiliary = None
        if len(ranked) > 1 and analysis.ambiguity_margin <= 0.12:
            auxiliary = ranked[1][0]
        del top_score
        risk = analysis.risk_level
        policy = derive_route_policy(risk, problem.problem_type)
        skills = [primary]
        if auxiliary:
            skills.append(auxiliary)
        skills.extend(["proof-obligation" if problem.problem_type == "proof" else "answer-normalization"])
        tools = ["answer_type_check"]
        if problem.answer_type in {"expression", "polynomial"}:
            tools.append("symbolic_equivalence")
        plan = RoutePlan(
            primary_subject=primary,
            auxiliary_subject=auxiliary,
            problem_type=problem.problem_type,
            answer_type=problem.answer_type,
            risk_level=risk,
            selected_skills=skills,
            selected_tools=tools,
            candidate_count=policy.candidate_count,
            max_reasoning_rounds=policy.max_reasoning_rounds,
            use_rag=policy.use_rag,
            use_lemma_loop=policy.use_lemma_loop,
            use_llm_finalizer=policy.use_llm_finalizer,
            method_families=method_families_for(primary, problem.problem_type),
            routing_confidence=analysis.confidence,
            ambiguity_margin=analysis.ambiguity_margin,
            complexity_flags=analysis.complexity_flags,
        )
        plan.validate()
        return plan

    @staticmethod
    def _complexity_flags(
        problem: ProblemIR,
        *,
        mixed_domain: bool,
    ) -> list[str]:
        lowered = problem.normalized_problem.lower()
        flags: list[str] = []
        if len(problem.normalized_problem) >= 600:
            flags.append("long_problem")
        if len(problem.assumptions) >= 3:
            flags.append("many_conditions")
        if len(problem.symbols) >= 6:
            flags.append("many_symbols")
        if any(marker in lowered for marker in ("piecewise", "absolute value", "|x|")):
            flags.append("piecewise_or_absolute")
        if any(
            marker in lowered
            for marker in (
                "if and only if",
                "iff",
                "converse",
                "necessary and sufficient",
                "interchange",
            )
        ):
            flags.append("theorem_direction_or_interchange")
        if (
            any(marker in lowered for marker in ("exist", "there is"))
            and any(marker in lowered for marker in ("unique", "uniqueness"))
        ):
            flags.append("existence_and_uniqueness")
        if any(
            marker in lowered
            for marker in ("ill-conditioned", "near singular", "unstable numerical")
        ):
            flags.append("ill_conditioned_numerics")
        if mixed_domain:
            flags.append("mixed_domain")
        if problem.problem_type in {"proof", "derivation"} or any(
            marker in lowered
            for marker in ("induction", "lemma", "case analysis", "contradiction")
        ):
            flags.append("proof_depth")
        return flags


class RouterPlanner:
    def __init__(
        self,
        rule_engine: RouterRuleEngine | None = None,
        contracts: PromptContractLoader | None = None,
    ) -> None:
        self._rules = rule_engine or RouterRuleEngine()
        self._contracts = contracts or PromptContractLoader()

    def plan(
        self,
        problem: ProblemIR,
        *,
        llm_chat: Callable[..., str] | None = None,
        consume_call: Callable[[], None] | None = None,
        max_tokens: int = 0,
        context_view: RoleContextView | None = None,
        record_prompt_chars: Callable[[int], None] | None = None,
    ) -> RoutePlan:
        rule_plan = self._rules.plan(problem)
        top_score = rule_plan.routing_confidence
        if top_score >= 0.75 or llm_chat is None or consume_call is None:
            return rule_plan
        try:
            consume_call()
            context = (
                f"\nAuthorized context view:\n{context_view.to_prompt_json()}"
                if context_view is not None
                else ""
            )
            user = (
                f"Problem:\n{problem.normalized_problem}\n\n"
                'Return {"primary_subject":"...","auxiliary_subject":null,'
                '"risk_level":"low|medium|high","method_families":["...","...","..."]}.'
                f"{context}"
            )
            messages = self._contracts.messages(
                "router_planner",
                user,
                "Classify the math domain and return JSON only.",
            )
            if record_prompt_chars is not None:
                record_prompt_chars(
                    sum(len(message["content"]) for message in messages)
                )
            response = llm_chat(
                messages=messages,
                temperature=0.0,
                max_tokens=max_tokens,
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
            risk_order = {"low": 0, "medium": 1, "high": 2}
            if risk_order[risk] < risk_order[rule_plan.risk_level]:
                risk = rule_plan.risk_level
            policy = derive_route_policy(risk, problem.problem_type)
            selected = [primary] + ([auxiliary] if auxiliary else [])
            selected.append("proof-obligation" if problem.problem_type == "proof" else "answer-normalization")
            planned = replace(
                rule_plan,
                primary_subject=primary,
                auxiliary_subject=auxiliary,
                risk_level=risk,
                selected_skills=selected,
                candidate_count=policy.candidate_count,
                max_reasoning_rounds=policy.max_reasoning_rounds,
                use_rag=policy.use_rag,
                use_lemma_loop=policy.use_lemma_loop,
                use_llm_finalizer=policy.use_llm_finalizer,
                method_families=method_families_for(primary, problem.problem_type),
            )
            planned.validate()
            return planned
        except (BudgetExceeded, ValueError, TypeError, json.JSONDecodeError, RuntimeError):
            return rule_plan
