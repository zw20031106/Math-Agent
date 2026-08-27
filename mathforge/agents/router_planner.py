from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Callable

from mathforge.agents.prompt_compiler import PromptCompiler
from mathforge.agents.registry import PromptContractLoader
from mathforge.agent_runtime.router_protocol import (
    AuthoritativePlan,
    ROUTER_INTENT_FIELDS,
    RouterPlanningOutcome,
    build_authoritative_plan,
    parse_router_intent,
)
from mathforge.context.snapshots import RoleContextView
from mathforge.context.errors import ContextBudgetExceeded
from mathforge.harness.errors import BudgetExceeded, ModelTransportError
from mathforge.harness.schemas import MethodFamily, ProblemIR, RoutePlan


_SUBJECT_SIGNALS: dict[str, tuple[tuple[str, float], ...]] = {
    "abstract-algebra": (
        ("抽象代数", 0.30),
        ("有限域", 0.28),
        ("\\mathbb f_", 0.30),
        ("不可约", 0.18),
        ("循环群", 0.28),
        ("交错群", 0.28),
        ("群同态", 0.30),
        ("商环", 0.30),
        ("理想", 0.22),
        ("sylow", 0.30),
        ("共轭类", 0.28),
        ("finite field", 0.28),
        ("quotient ring", 0.28),
    ),
    "advanced-linear-algebra": (
        ("高等代数", 0.30),
        ("jordan", 0.30),
        ("矩阵", 0.12),
        ("行列式", 0.18),
        ("特征值", 0.22),
        ("特征多项式", 0.26),
        ("最小多项式", 0.28),
        ("中心化子", 0.30),
        ("kronecker", 0.28),
        ("秩", 0.18),
        ("零度", 0.20),
        ("二次型", 0.26),
        ("惯性指数", 0.28),
        ("幂零", 0.24),
        ("\\det", 0.24),
    ),
    "advanced-real-analysis": (
        ("数学分析", 0.30),
        ("极限", 0.16),
        ("级数", 0.18),
        ("幂级数", 0.24),
        ("收敛区间", 0.26),
        ("\\int", 0.12),
        ("\\sum", 0.12),
        ("g=f^{-1}", 0.24),
        ("反函数", 0.22),
        ("\\|f_n\\|_\\infty", 0.24),
    ),
    "functional-analysis": (
        ("泛函分析", 0.30),
        ("算子", 0.22),
        ("谱", 0.22),
        ("hilbert 空间", 0.28),
        ("线性泛函", 0.30),
        ("volterra", 0.30),
        ("单边右移", 0.30),
        ("算子范数", 0.30),
        ("谱半径", 0.28),
        ("\\operatorname{span}", 0.28),
        ("到子空间", 0.24),
        (" operator", 0.18),
    ),
    "measure-integration": (
        ("测度", 0.30),
        ("lebesgue", 0.30),
        ("tonelli", 0.32),
        ("fubini", 0.30),
        ("\\mathbf1", 0.24),
        ("l^2(0,1)", 0.18),
        ("l^3(0,1)", 0.24),
        ("smith–volterra", 0.32),
        ("smith-volterra", 0.32),
        ("\\lim_{n\\to\\infty}\\int", 0.12),
        ("\\int_0^1\\int_0^1", 0.28),
    ),
    "ordinary-differential-equations": (
        ("常微分方程", 0.32),
        ("初值问题", 0.28),
        ("y'=", 0.20),
        ("y''", 0.22),
        ("x'=a", 0.24),
        ("euler 方程", 0.28),
        ("ordinary differential", 0.28),
        (" ode ", 0.28),
    ),
    "partial-differential-equations": (
        ("偏微分方程", 0.32),
        ("热方程", 0.30),
        ("波动方程", 0.30),
        ("\\Delta u", 0.28),
        ("\\delta u", 0.28),
        ("单位圆盘", 0.24),
        ("u_t=", 0.24),
        ("u_{tt}", 0.24),
        ("边界", 0.10),
        ("partial differential", 0.28),
        (" pde ", 0.28),
    ),
    "stochastic-processes": (
        ("随机过程", 0.32),
        ("brownian", 0.32),
        ("markov 链", 0.32),
        ("poisson 过程", 0.50),
        ("平稳分布", 0.28),
        ("首次离开", 0.24),
        ("stopping time", 0.28),
    ),
    "operations-research": (
        ("运筹学", 0.32),
        ("线性规划", 0.30),
        ("对偶问题", 0.28),
        ("最短路", 0.30),
        ("最大流", 0.30),
        ("网络容量", 0.26),
        ("指派问题", 0.30),
        ("零和博弈", 0.30),
        ("博弈值", 0.26),
        ("operations research", 0.30),
    ),
    "regression": (
        ("线性回归", 0.32),
        ("x^tx", 0.30),
        ("最小二乘", 0.28),
        ("ridge", 0.30),
        ("帽子矩阵", 0.30),
        ("留一法残差", 0.30),
        ("残差平方和", 0.26),
        ("回归模型", 0.28),
    ),
    "differential-geometry": (
        ("微分几何", 0.32),
        ("gaussian 曲率", 0.32),
        ("测地曲率", 0.32),
        ("环面参数", 0.28),
        ("球面", 0.16),
        ("differential geometry", 0.30),
    ),
    "complex-analysis": (
        ("复分析", 0.30),
        ("复变", 0.28),
        ("\\oint", 0.28),
        ("留数", 0.30),
        ("rouché", 0.32),
        ("rouche", 0.32),
        ("整函数", 0.28),
        ("无穷远点", 0.26),
        ("taylor", 0.18),
        ("holomorphic", 0.28),
        ("residue", 0.28),
        ("complex plane", 0.24),
        ("\\int_{-\\infty}^{\\infty}", 0.24),
    ),
    "numerical-analysis": (
        ("数值分析", 0.32),
        ("simpson", 0.30),
        ("newton 法", 0.30),
        ("hermite 插值", 0.30),
        ("gauss–seidel", 0.32),
        ("gauss-seidel", 0.32),
        ("条件数", 0.28),
        ("迭代矩阵", 0.26),
        ("有符号误差", 0.26),
        ("rounding error", 0.24),
        ("numerical", 0.20),
    ),
    "probability": (
        ("概率论", 0.30),
        ("概率", 0.16),
        ("期望", 0.16),
        ("方差", 0.16),
        ("随机变量", 0.22),
        ("poisson(", 0.24),
        ("poisson", 0.28),
        ("正态分布", 0.24),
        ("n(0,1)", 0.24),
        ("指数随机变量", 0.24),
        ("随机游走", 0.24),
        ("后验概率", 0.26),
        ("次序统计量", 0.26),
        ("probability", 0.08),
        ("random variable", 0.08),
    ),
    "statistics": (
        ("统计推断", 0.32),
        ("最大似然", 0.30),
        ("fisher 信息", 0.30),
        ("cramér–rao", 0.32),
        ("cramer-rao", 0.32),
        ("估计量", 0.22),
        ("样本来自", 0.18),
        ("样本容量", 0.14),
        ("statistics", 0.18),
        ("estimator", 0.18),
    ),
    "topology": (
        ("拓扑学", 0.32),
        ("同调群", 0.32),
        ("同胚", 0.26),
        ("genus", 0.26),
        ("映射度数", 0.30),
        ("t^2", 0.18),
        ("topology", 0.28),
        ("homeomorph", 0.26),
    ),
    "algebra": (
        ("方程", 0.08),
        ("多项式", 0.08),
        ("inequality", 0.08),
        ("polynomial", 0.08),
        ("equation", 0.08),
    ),
    "calculus": (
        ("derivative", 0.08),
        ("integral", 0.08),
        ("limit", 0.08),
    ),
    "combinatorics": (
        ("排列", 0.08),
        ("组合", 0.08),
        ("计数", 0.08),
        ("permutation", 0.08),
        ("combination", 0.08),
        ("counting", 0.08),
    ),
    "differential-equations": (
        ("differential equation", 0.16),
        ("ode", 0.08),
        ("pde", 0.08),
    ),
    "discrete-math": (
        ("图论", 0.08),
        ("递推", 0.08),
        ("graph", 0.08),
        ("recurrence", 0.08),
    ),
    "geometry": (
        ("三角形", 0.08),
        ("圆", 0.08),
        ("几何", 0.08),
        ("triangle", 0.08),
        ("circle", 0.08),
        ("angle", 0.08),
    ),
    "linear-algebra": (
        ("matrix", 0.08),
        ("vector", 0.08),
        ("eigenvalue", 0.08),
    ),
    "logic": (
        ("命题", 0.08),
        ("谓词", 0.08),
        ("逻辑", 0.08),
        ("predicate", 0.08),
        ("logic", 0.08),
    ),
    "number-theory": (
        ("素数", 0.16),
        ("整除", 0.16),
        ("同余", 0.16),
        ("prime", 0.08),
        ("divisib", 0.08),
        ("modulo", 0.08),
    ),
    "optimization": (
        ("最优化", 0.18),
        ("最大值", 0.08),
        ("最小值", 0.08),
        ("optimization", 0.08),
        ("maximum", 0.08),
        ("minimum", 0.08),
    ),
    "real-analysis": (
        ("real analysis", 0.16),
        ("uniform convergence", 0.16),
        ("measure", 0.16),
    ),
    "set-theory": (
        ("集合", 0.08),
        ("基数", 0.16),
        ("set theory", 0.16),
        ("cardinality", 0.16),
    ),
}

_METHOD_FAMILIES: dict[str, tuple[str, str, str]] = {
    "abstract-algebra": (
        "structural-transform",
        "factorization-invariant",
        "contradiction-extremal",
    ),
    "advanced-linear-algebra": (
        "row-space",
        "spectral",
        "linear-map-invariant",
    ),
    "advanced-real-analysis": (
        "direct-analytic",
        "change-of-variable",
        "estimate-limit",
    ),
    "functional-analysis": (
        "spectral",
        "direct-analytic",
        "estimate-limit",
    ),
    "measure-integration": (
        "direct-analytic",
        "change-of-variable",
        "estimate-limit",
    ),
    "ordinary-differential-equations": (
        "substitution-elimination",
        "spectral",
        "constructive-computation",
    ),
    "partial-differential-equations": (
        "spectral",
        "change-of-variable",
        "estimate-limit",
    ),
    "stochastic-processes": (
        "conditioning",
        "distribution-transform",
        "indicator-linearity",
    ),
    "operations-research": (
        "duality-transform",
        "constructive-computation",
        "invariant-extremal",
    ),
    "regression": (
        "row-space",
        "spectral",
        "convexity-inequality",
    ),
    "differential-geometry": (
        "direct-analytic",
        "vector-transformation",
        "structural-transform",
    ),
    "algebra": ("substitution-elimination", "factorization-invariant", "structural-transform"),
    "geometry": ("synthetic-geometry", "coordinate-geometry", "vector-transformation"),
    "number-theory": ("congruence", "valuation-factorization", "descent-extremal"),
    "combinatorics": ("bijection-counting", "recurrence-generating", "invariant-extremal"),
    "probability": ("conditioning", "indicator-linearity", "distribution-transform"),
    "calculus": ("direct-analytic", "change-of-variable", "estimate-limit"),
    "linear-algebra": ("row-space", "spectral", "linear-map-invariant"),
    "optimization": ("calculus-stationarity", "convexity-inequality", "duality-transform"),
    "logic": ("direct-deduction", "contradiction", "model-counterexample"),
    "complex-analysis": ("direct-analytic", "structural-transform", "contradiction-extremal"),
    "differential-equations": (
        "substitution-elimination",
        "spectral",
        "constructive-computation",
    ),
    "discrete-math": (
        "recurrence-generating",
        "invariant-extremal",
        "constructive-computation",
    ),
    "numerical-analysis": (
        "constructive-computation",
        "estimate-limit",
        "spectral",
    ),
    "real-analysis": ("direct-analytic", "change-of-variable", "estimate-limit"),
    "set-theory": ("direct-deduction", "model-counterexample", "structural-transform"),
    "statistics": ("conditioning", "direct-analytic", "indicator-linearity"),
    "topology": ("structural-transform", "invariant-extremal", "contradiction"),
    "general-math": ("direct-deduction", "constructive-computation", "contradiction-extremal"),
}
_HIGH_DIFFICULTY_FEATURES = frozenset(
    {
        "nested_aggregation",
        "asymptotic_cancellation",
        "spectral_inference",
        "state_dependent_probability",
        "coupled_congruences",
        "surjective_counting",
        "radical_domain_constraints",
        "multivariable_global_constraint",
        "higher_order_differential_system",
        "singular_or_special_integral",
        "parameter_regime",
        "multiple_targets",
        "long_condition_chain",
        "nested_quantifiers",
        "bidirectional_proof",
        "multi_stage_proof",
        "candidate_conflict",
    }
)


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
    trigger_reasons: list[str]


def derive_route_policy(risk_level: str, problem_type: str) -> RoutePolicy:
    if risk_level not in {"low", "medium", "high"}:
        raise ValueError(f"unsupported risk level: {risk_level}")
    return RoutePolicy(
        candidate_count={"low": 2, "medium": 2, "high": 3}[risk_level],
        max_reasoning_rounds=3 if risk_level == "high" else 1,
        use_rag=risk_level in {"medium", "high"},
        use_lemma_loop=(
            risk_level == "high"
            and problem_type in {"proof", "derivation"}
        ),
        use_llm_finalizer=problem_type in {"proof", "explanation"},
    )


_SIMPLE_DIRECT_PROBLEM_TYPES = frozenset(
    {"calculation", "fill_blank", "multiple_choice"}
)
_LONG_HORIZON_COMPLEXITY_FLAGS = frozenset(
    {
        "long_problem",
        "many_conditions",
        "many_symbols",
        "piecewise_or_absolute",
        "theorem_direction_or_interchange",
        "existence_and_uniqueness",
        "proof_depth",
        "mixed_domain",
        "candidate_conflict",
        "multiple_targets",
        "long_condition_chain",
        "nested_quantifiers",
        "multi_stage_proof",
    }
)


def simple_direct_candidate_reasons(
    problem: ProblemIR,
    route: RoutePlan,
) -> tuple[str, ...]:
    """Return deterministic blockers for E2's one-call simple path."""

    reasons: list[str] = []
    if problem.problem_type not in _SIMPLE_DIRECT_PROBLEM_TYPES:
        reasons.append("problem_type_not_simple")
    if route.risk_level == "high":
        reasons.append("route_risk_high")
    confidence_only_ambiguities = {
        "low_answer_type_confidence",
        "low_target_confidence",
        "low_response_mode_confidence",
    }
    substantive_ambiguities = tuple(
        item
        for item in getattr(problem, "ambiguities", ())
        if item not in confidence_only_ambiguities
    )
    if bool(getattr(problem, "requires_router_disambiguation", False)) and (
        substantive_ambiguities
        or tuple(getattr(problem, "interpretation_conflicts", ()))
    ):
        reasons.append("router_disambiguation_required")
    if substantive_ambiguities or tuple(
        getattr(problem, "interpretation_conflicts", ())
    ):
        reasons.append("problem_ambiguity_present")
    if route.ambiguity_margin < 0.12 and route.auxiliary_subject:
        reasons.append("route_subject_ambiguity")
    if route.max_reasoning_rounds > 1:
        reasons.append("long_horizon_rounds_required")
    if _LONG_HORIZON_COMPLEXITY_FLAGS.intersection(route.complexity_flags):
        reasons.append("long_horizon_complexity_flag")
    if route.use_lemma_loop or route.use_llm_finalizer:
        reasons.append("downstream_long_horizon_stage_required")
    return tuple(dict.fromkeys(reasons))


def is_simple_direct_candidate(problem: ProblemIR, route: RoutePlan) -> bool:
    return not simple_direct_candidate_reasons(problem, route)


def method_families_for(subject: str, problem_type: str) -> list[str]:
    families = list(_METHOD_FAMILIES.get(subject, _METHOD_FAMILIES["general-math"]))
    if problem_type == "proof" and "contradiction" not in " ".join(families):
        families[-1] = "contradiction-or-extremal"
    return families


def selected_skills_for(
    problem: ProblemIR,
    *,
    primary_subject: str,
    auxiliary_subject: str | None,
    risk_level: str,
) -> list[str]:
    skills = [primary_subject]
    if auxiliary_subject:
        skills.append(auxiliary_subject)
    skills.append("answer-normalization")
    if problem.problem_type in {"proof", "derivation"}:
        skills.append("proof-obligation")
    if risk_level in {"medium", "high"}:
        skills.append("counterexample-search")
    if (
        primary_subject != "general-math"
        and problem.answer_type in {"expression", "polynomial"}
    ):
        skills.append("symbolic-equivalence")
    if (
        primary_subject == "numerical-analysis"
        or auxiliary_subject == "numerical-analysis"
        or any(
            marker in problem.normalized_problem.lower()
            for marker in (
                "数值",
                "误差",
                "近似",
                "条件数",
                "ill-conditioned",
                "numerical",
            )
        )
    ):
        skills.append("numerical-stability")
    if risk_level == "high" and problem.problem_type in {"proof", "derivation"}:
        skills.append("lemma-compression")
    return list(dict.fromkeys(skills))


def selected_tools_for(
    problem: ProblemIR,
    *,
    primary_subject: str,
    auxiliary_subject: str | None,
) -> list[str]:
    subjects = {primary_subject, auxiliary_subject}
    lowered = problem.normalized_problem.lower()
    tools = [
        "answer_type_check",
        "latex_syntax_check",
    ]
    if (
        problem.answer_type in {"expression", "fraction", "polynomial"}
        or subjects.intersection(
            {
                "algebra",
                "calculus",
                "complex-analysis",
                "differential-equations",
                "general-math",
                "number-theory",
            }
        )
    ):
        tools.extend(
            [
                "safe_parse_expression",
                "simplify_expression",
                "symbolic_equivalence",
            ]
        )
    if (
        "numerical-analysis" in subjects
        or any(
            marker in lowered
            for marker in ("数值", "近似", "误差", "numerical", "residual")
        )
    ):
        tools.append("numerical_residual")
    if (
        problem.answer_type == "matrix"
        or subjects.intersection(
            {"linear-algebra", "advanced-linear-algebra", "regression"}
        )
    ):
        tools.append("matrix_shape_check")
    if subjects.intersection({"probability", "statistics", "stochastic-processes"}):
        tools.append("density_normalization")
    if subjects.intersection(
        {"combinatorics", "discrete-math", "operations-research"}
    ):
        tools.append("small_case_enumeration")
    return list(dict.fromkeys(tools))


class RouterRuleEngine:
    def rank(self, problem: ProblemIR) -> list[tuple[str, float]]:
        lowered = problem.normalized_problem.lower()
        scores: list[tuple[str, float, float]] = []
        for subject, signals in _SUBJECT_SIGNALS.items():
            signal_score = sum(weight for signal, weight in signals if signal in lowered)
            if signal_score:
                scores.append(
                    (
                        subject,
                        round(min(0.98, 0.72 + signal_score), 2),
                        signal_score,
                    )
                )
        ranked = sorted(scores, key=lambda item: (-item[2], item[0]))
        return [(subject, confidence) for subject, confidence, _ in ranked] or [
            ("general-math", 0.4)
        ]

    def trigger_reasons(
        self,
        problem: ProblemIR,
        *,
        limit: int = 2,
    ) -> list[str]:
        lowered = problem.normalized_problem.lower()
        ranked_subjects = [subject for subject, _ in self.rank(problem)[:limit]]
        reasons: list[str] = []
        for subject in ranked_subjects:
            if subject == "general-math":
                reasons.append("general-math:no_registered_subject_trigger")
                continue
            matches = [
                signal
                for signal, _ in _SUBJECT_SIGNALS[subject]
                if signal in lowered
            ]
            reasons.append(
                f"{subject}:matched:{','.join(matches[:6])}"
            )
        return reasons

    @staticmethod
    def subjects() -> list[str]:
        return sorted({*_SUBJECT_SIGNALS, "general-math"})

    def analyze(self, problem: ProblemIR) -> RouteAnalysis:
        ranked = self.rank(problem)
        confidence = ranked[0][1]
        ambiguity_margin = (
            round(confidence - ranked[1][1], 4) if len(ranked) > 1 else 1.0
        )
        complexity_flags = self._complexity_flags(
            problem,
            mixed_domain=len(ranked) > 1 and ambiguity_margin <= 0.12,
            missing_dedicated_skill=ranked[0][0] == "general-math",
        )
        long_reasoning = "long_reasoning" in problem.risk_flags
        structural_high = bool(
            _HIGH_DIFFICULTY_FEATURES.intersection(
                problem.difficulty_features
            )
        )
        if structural_high or len(complexity_flags) >= 4 or (
            long_reasoning and len(complexity_flags) >= 2
        ):
            risk = "high"
        elif long_reasoning or complexity_flags or confidence < 0.75:
            risk = "medium"
        else:
            risk = "low"
        return RouteAnalysis(
            subject_candidates=ranked,
            confidence=confidence,
            ambiguity_margin=ambiguity_margin,
            complexity_flags=complexity_flags,
            risk_level=risk,
            trigger_reasons=self.trigger_reasons(problem),
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
        skills = selected_skills_for(
            problem,
            primary_subject=primary,
            auxiliary_subject=auxiliary,
            risk_level=risk,
        )
        tools = selected_tools_for(
            problem,
            primary_subject=primary,
            auxiliary_subject=auxiliary,
        )
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
        missing_dedicated_skill: bool,
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
        if problem.parser_confidence < 0.70:
            flags.append("low_parser_confidence")
        if missing_dedicated_skill:
            flags.append("general_math_fallback")
        flags.extend(
            f"structure:{feature}"
            for feature in problem.difficulty_features
        )
        confidence_only_ambiguities = {
            "low_answer_type_confidence",
            "low_target_confidence",
            "low_response_mode_confidence",
        }
        if any(
            ambiguity not in confidence_only_ambiguities
            for ambiguity in problem.ambiguities
        ):
            flags.append("problem_ir_ambiguity")
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
        self._compiler = PromptCompiler(self._contracts)

    def routing_reasons(
        self,
        problem: ProblemIR,
        plan: RoutePlan | None = None,
    ) -> list[str]:
        reasons = self._rules.trigger_reasons(problem)
        deterministic_primary = (
            problem.subject_candidates[0][0]
            if problem.subject_candidates
            else "general-math"
        )
        if plan is not None and plan.primary_subject != deterministic_primary:
            reasons.insert(
                0,
                f"llm_router:primary_subject:{plan.primary_subject}",
            )
        return reasons

    def plan(
        self,
        problem: ProblemIR,
        *,
        llm_chat: Callable[..., str] | None = None,
        consume_call: Callable[[], None] | None = None,
        max_tokens: int = 0,
        context_view: RoleContextView | None = None,
        record_prompt_chars: Callable[[int], None] | None = None,
        record_prompt_components: Callable[[dict[str, int]], None] | None = None,
        record_protocol_telemetry: Callable[
            [int | None, str, str, str], None
        ]
        | None = None,
    ) -> RoutePlan:
        return self.plan_authoritative(
            problem,
            llm_chat=llm_chat,
            consume_call=consume_call,
            max_tokens=max_tokens,
            context_view=context_view,
            record_prompt_chars=record_prompt_chars,
            record_prompt_components=record_prompt_components,
            record_protocol_telemetry=record_protocol_telemetry,
        ).route_plan

    def plan_authoritative(
        self,
        problem: ProblemIR,
        *,
        llm_chat: Callable[..., str] | None = None,
        consume_call: Callable[[], None] | None = None,
        max_tokens: int = 0,
        context_view: RoleContextView | None = None,
        record_prompt_chars: Callable[[int], None] | None = None,
        record_prompt_components: Callable[[dict[str, int]], None] | None = None,
        record_protocol_telemetry: Callable[
            [int | None, str, str, str], None
        ]
        | None = None,
        previous_plan: AuthoritativePlan | None = None,
        verified_fact_ids: tuple[str, ...] = (),
    ) -> RouterPlanningOutcome:
        rule_plan = self._rules.plan(problem)
        if llm_chat is None or consume_call is None:
            fallback = build_authoritative_plan(
                problem,
                rule_plan,
                None,
                source="router_rule_fallback",
                fallback_reason="router_model_unavailable",
                previous=previous_plan,
                verified_fact_ids=verified_fact_ids,
            )
            return RouterPlanningOutcome(
                rule_plan,
                fallback,
                False,
                "router_rule_fallback",
                "router_model_unavailable",
            )
        try:
            consume_call()
            context = (
                f"\nAuthorized context view:\n{context_view.to_prompt_json()}"
                if context_view is not None
                else ""
            )
            prior_context = (
                "\n\nReplan from this public prior plan without changing the "
                "original conditions or verified facts:\n"
                + json.dumps(
                    {
                        "prior_plan": previous_plan.to_dict(),
                        "verified_fact_ids": list(verified_fact_ids),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                if previous_plan is not None
                else ""
            )
            if problem.requires_router_disambiguation:
                problem_text = problem.raw_problem
                interpretation_context = (
                    "\n\nParser interpretation requiring disambiguation:\n"
                    + json.dumps(
                        {
                            "target_phrase": problem.target_phrase,
                            "target_confidence": problem.target_confidence,
                            "answer_type": problem.answer_type,
                            "answer_type_confidence": (
                                problem.answer_type_confidence
                            ),
                            "response_mode": problem.response_mode,
                            "response_mode_confidence": (
                                problem.response_mode_confidence
                            ),
                            "conflicts": problem.interpretation_conflicts,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + "\nUse the exact full original problem above to resolve "
                    "the intended target; do not discard conditions."
                )
            else:
                problem_text = problem.normalized_problem
                interpretation_context = ""
            user = (
                f"Problem:\n{problem_text}{interpretation_context}\n\n"
                "Return only the mathematical routing intent using the exact "
                "RouterIntent schema. The Host owns subgoals, tasks, Agent "
                f"assignments, the DAG, budgets, and plan IDs.{prior_context}{context}"
            )
            compilation = self._compiler.compile_role(
                "router_planner",
                user_content=user,
                runtime_instructions=(
                    "Classify the mathematical intent and return JSON only. "
                    f"Required fields: {', '.join(sorted(ROUTER_INTENT_FIELDS))}. "
                    "Allowed domains: "
                    + ", ".join(sorted({*_SUBJECT_SIGNALS, "general-math"}))
                    + ". Allowed methods: "
                    + ", ".join(item.value for item in MethodFamily)
                    + "."
                ),
            )
            messages = compilation.messages
            if record_prompt_chars is not None:
                record_prompt_chars(
                    sum(len(message["content"]) for message in messages)
                )
            if record_prompt_components is not None:
                record_prompt_components(compilation.prompt_component_tokens)
            response = llm_chat(
                messages=messages,
                temperature=0.0,
                max_tokens=PromptCompiler.bounded_output_tokens(
                    max_tokens,
                    compilation.max_output_tokens,
                ),
            )
            intent, parse_tier, recovery_reason, degradation = parse_router_intent(
                response,
                allowed_domains={*_SUBJECT_SIGNALS, "general-math"},
            )
            if record_protocol_telemetry is not None:
                record_protocol_telemetry(
                    getattr(response, "model_call_index", None),
                    parse_tier,
                    recovery_reason,
                    degradation,
                )
            primary = intent.primary_domain
            auxiliary = intent.secondary_domain
            risk = intent.risk
            risk_order = {"low": 0, "medium": 1, "high": 2}
            if risk_order[risk] < risk_order[rule_plan.risk_level]:
                risk = rule_plan.risk_level
            if intent.needs_long_horizon and risk_order[risk] < risk_order["medium"]:
                risk = "medium"
            policy = derive_route_policy(risk, problem.problem_type)
            methods = list(
                dict.fromkeys(
                    [*intent.method_families, *rule_plan.method_families]
                )
            )[: max(1, policy.candidate_count)]
            selected = selected_skills_for(
                problem,
                primary_subject=primary,
                auxiliary_subject=auxiliary,
                risk_level=risk,
            )
            selected_tools = selected_tools_for(
                problem,
                primary_subject=primary,
                auxiliary_subject=auxiliary,
            )
            planned = replace(
                rule_plan,
                primary_subject=primary,
                auxiliary_subject=auxiliary,
                risk_level=risk,
                selected_skills=selected,
                selected_tools=selected_tools,
                candidate_count=policy.candidate_count,
                max_reasoning_rounds=policy.max_reasoning_rounds,
                use_rag=policy.use_rag,
                use_lemma_loop=policy.use_lemma_loop,
                use_llm_finalizer=policy.use_llm_finalizer,
                method_families=methods,
                complexity_flags=list(
                    dict.fromkeys(
                        [
                            *rule_plan.complexity_flags,
                            *(("router_long_horizon",) if intent.needs_long_horizon else ()),
                            *(
                                f"router_pattern:{pattern}"
                                for pattern in intent.patterns
                            ),
                        ]
                    )
                ),
            )
            planned.validate()
            authoritative = build_authoritative_plan(
                problem,
                planned,
                None,
                source="llm_router",
                previous=previous_plan,
                verified_fact_ids=verified_fact_ids,
            )
            return RouterPlanningOutcome(
                planned,
                authoritative,
                True,
                "llm_router",
                protocol_parse_tier=parse_tier,
                protocol_recovery_reason=recovery_reason,
                protocol_assurance_degradation=degradation,
            )
        except (
            BudgetExceeded,
            ContextBudgetExceeded,
            ModelTransportError,
            ValueError,
            TypeError,
            json.JSONDecodeError,
            RuntimeError,
        ) as error:
            if record_protocol_telemetry is not None:
                record_protocol_telemetry(
                    getattr(locals().get("response", ""), "model_call_index", None),
                    "rejected",
                    _router_failure_reason(error),
                    "unusable",
                )
            failure_reason = _router_failure_reason(error)
            fallback = build_authoritative_plan(
                problem,
                rule_plan,
                None,
                source="router_rule_fallback",
                fallback_reason=failure_reason,
                previous=previous_plan,
                verified_fact_ids=verified_fact_ids,
            )
            return RouterPlanningOutcome(
                rule_plan,
                fallback,
                True,
                "router_rule_fallback",
                failure_reason,
            )


def _router_failure_reason(error: Exception) -> str:
    if isinstance(error, BudgetExceeded):
        return "router_budget_unavailable"
    if isinstance(error, ContextBudgetExceeded):
        return "router_context_infeasible"
    if isinstance(error, ModelTransportError):
        return f"router_{error.code}"
    if isinstance(error, json.JSONDecodeError):
        return "router_json_invalid"
    if isinstance(error, (ValueError, TypeError)):
        text = str(error).lower()
        if "cycle" in text:
            return "router_subgoal_cycle"
        if "method" in text:
            return "router_method_invalid"
        return "router_schema_invalid"
    return "router_execution_failed"
