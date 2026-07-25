from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Callable, Mapping, Protocol

from mathforge.agents.router_planner import RouterRuleEngine
from mathforge.agents.solver import AlternativeSolver, PrimarySolver, SolverRequest
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.parsing.solution_parser import SolutionParser


class InjectedChatClient(Protocol):
    def chat(
        self,
        *,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> str: ...


@dataclass(frozen=True)
class PromptProbeCase:
    case_id: str
    category: str
    problem: str
    answer_type: str
    method_family: str
    role: str = "PrimarySolver"


PROMPT_CONTRACT_PROBE_CASES = (
    PromptProbeCase("scalar-1", "scalar", "计算 17+28。", "integer", "direct-deduction"),
    PromptProbeCase(
        "scalar-2",
        "scalar",
        "解方程 3x-5=10。",
        "expression",
        "substitution-elimination",
        "AlternativeSolver",
    ),
    PromptProbeCase(
        "scalar-3",
        "scalar",
        "求极限 lim_{x→0} sin(x)/x。",
        "integer",
        "direct-analytic",
    ),
    PromptProbeCase(
        "scalar-4",
        "scalar",
        "求函数 x^2-4x+7 的最小值。",
        "integer",
        "calculus-stationarity",
        "AlternativeSolver",
    ),
    PromptProbeCase(
        "scalar-5",
        "scalar",
        "计算组合数 C(10,2)。",
        "integer",
        "bijection-counting",
    ),
    PromptProbeCase(
        "linear-input-scalar-1",
        "linear_input_scalar",
        "给定矩阵 [[1,2],[3,4]]，求其行列式。",
        "integer",
        "row-space",
    ),
    PromptProbeCase(
        "linear-input-scalar-2",
        "linear_input_scalar",
        "向量 (1,2,3) 与 (4,5,6) 的内积是多少？",
        "integer",
        "vector-transformation",
        "AlternativeSolver",
    ),
    PromptProbeCase(
        "linear-input-scalar-3",
        "linear_input_scalar",
        "矩阵 [[2,0],[0,3]] 的迹是多少？",
        "integer",
        "spectral",
    ),
    PromptProbeCase(
        "interval-input-number-1",
        "interval_input_numeric",
        "在区间 [0,2] 上求 x^2 的最大值。",
        "integer",
        "calculus-stationarity",
    ),
    PromptProbeCase(
        "interval-input-number-2",
        "interval_input_numeric",
        "函数 x(1-x) 在区间 [0,1] 上的最大值是多少？",
        "fraction",
        "convexity-inequality",
        "AlternativeSolver",
    ),
    PromptProbeCase(
        "polynomial-1",
        "polynomial",
        "分解多项式 x^2-1。",
        "polynomial",
        "factorization-invariant",
    ),
    PromptProbeCase(
        "polynomial-2",
        "polynomial",
        "求多项式 (x+1)^3 的展开式。",
        "polynomial",
        "structural-transform",
        "AlternativeSolver",
    ),
    PromptProbeCase(
        "set-group-1",
        "set_or_group",
        "求集合 {1,2,3} 的幂集元素个数。",
        "integer",
        "bijection-counting",
    ),
    PromptProbeCase(
        "set-group-2",
        "set_or_group",
        "说明整数模 5 加法群的单位元。",
        "algebraic_structure",
        "direct-deduction",
        "AlternativeSolver",
    ),
    PromptProbeCase(
        "proof-1",
        "proof_or_derivation",
        "证明任意实数 x 都有 x^2≥0。",
        "text",
        "direct-deduction",
    ),
    PromptProbeCase(
        "proof-2",
        "proof_or_derivation",
        "推导等差数列前 n 项和公式。",
        "expression",
        "constructive-computation",
    ),
    PromptProbeCase(
        "proof-3",
        "proof_or_derivation",
        "证明素数有无穷多个。",
        "text",
        "contradiction",
        "AlternativeSolver",
    ),
    PromptProbeCase(
        "cross-domain-1",
        "cross_domain",
        "用矩阵方法求二状态马尔可夫链一步后的概率。",
        "vector",
        "distribution-transform",
    ),
    PromptProbeCase(
        "cross-domain-2",
        "cross_domain",
        "求单位圆上随机点横坐标的期望。",
        "integer",
        "conditioning",
        "AlternativeSolver",
    ),
    PromptProbeCase(
        "cross-domain-3",
        "cross_domain",
        "用生成函数求斐波那契递推的通项。",
        "expression",
        "recurrence-generating",
    ),
)


@dataclass(frozen=True)
class PromptContractProbeMetrics:
    total: int
    strict_json_count: int
    host_owned_deviation_count: int
    candidate_deviation_count: int
    claims_nonempty_count: int
    public_steps_count: int
    final_answer_count: int
    method_family_match_count: int
    private_reasoning_field_count: int

    def to_dict(self) -> dict[str, int | float]:
        divisor = max(1, self.total)
        return {
            **asdict(self),
            "strict_json_rate": self.strict_json_count / divisor,
            "candidate_deviation_rate": self.candidate_deviation_count / divisor,
            "claims_nonempty_rate": self.claims_nonempty_count / divisor,
            "public_steps_rate": self.public_steps_count / divisor,
            "final_answer_rate": self.final_answer_count / divisor,
            "method_family_match_rate": self.method_family_match_count / divisor,
        }


@dataclass(frozen=True)
class PromptContractProbeReport:
    metrics: PromptContractProbeMetrics
    records: list[dict[str, object]]
    acceptance_errors: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "metrics": self.metrics.to_dict(),
            "records": list(self.records),
            "acceptance_errors": list(self.acceptance_errors),
        }


def run_live_prompt_contract_probe(
    client: InjectedChatClient,
    *,
    max_tokens: int,
    on_response: Callable[[PromptProbeCase, str], None] | None = None,
) -> PromptContractProbeReport:
    """Run the fixed 20-case probe through only an injected official chat client."""
    if max_tokens < 1:
        raise ValueError("max_tokens must be positive")
    parser = ProblemParser()
    router = RouterRuleEngine()
    responses: dict[str, str] = {}
    for case in PROMPT_CONTRACT_PROBE_CASES:
        problem = parser.parse(case.problem)
        route = router.plan(problem)
        request = SolverRequest(
            candidate_id=f"probe-{case.case_id}",
            problem=problem,
            route=route,
            skill_context="",
            method_family=case.method_family,
        )
        solver = (
            AlternativeSolver()
            if case.role == "AlternativeSolver"
            else PrimarySolver()
        )
        response = client.chat(
            messages=solver.build_messages(request),
            temperature=0.0,
            max_tokens=max_tokens,
        )
        responses[case.case_id] = str(response)
        if on_response is not None:
            on_response(case, str(response))
    return assess_prompt_contract_responses(responses)


def assess_prompt_contract_responses(
    responses: Mapping[str, str],
) -> PromptContractProbeReport:
    expected_ids = {case.case_id for case in PROMPT_CONTRACT_PROBE_CASES}
    if set(responses) != expected_ids:
        missing = sorted(expected_ids - set(responses))
        unexpected = sorted(set(responses) - expected_ids)
        raise ValueError(
            f"probe response IDs mismatch; missing={missing}, unexpected={unexpected}"
        )
    solution_parser = SolutionParser()
    records: list[dict[str, object]] = []
    strict_count = 0
    host_deviations = 0
    candidate_deviations = 0
    claims_nonempty = 0
    public_steps = 0
    final_answers = 0
    method_matches = 0
    private_fields = 0
    for case in PROMPT_CONTRACT_PROBE_CASES:
        response = str(responses[case.case_id])
        candidate = solution_parser.parse(
            response,
            candidate_id=f"probe-{case.case_id}",
            role=case.role,
            answer_type=case.answer_type,
        )
        own_host_deviations = [
            item
            for item in candidate.contract_deviations
            if item.endswith(":host_owned")
        ]
        has_private_field = _contains_private_reasoning_field(response)
        strict_count += candidate.parse_status == "strict_json"
        host_deviations += len(own_host_deviations)
        candidate_deviations += bool(candidate.contract_deviations)
        claims_nonempty += bool(candidate.claims)
        public_steps += bool(candidate.public_solution_steps)
        final_answers += bool(candidate.final_answer.strip())
        method_matches += candidate.method == case.method_family
        private_fields += has_private_field
        records.append(
            {
                "case_id": case.case_id,
                "category": case.category,
                "role": case.role,
                "parse_status": candidate.parse_status,
                "contract_deviations": list(candidate.contract_deviations),
                "host_owned_deviations": own_host_deviations,
                "claims_nonempty": bool(candidate.claims),
                "public_steps_present": bool(candidate.public_solution_steps),
                "final_answer_present": bool(candidate.final_answer.strip()),
                "method_family_match": candidate.method == case.method_family,
                "private_reasoning_field": has_private_field,
            }
        )
    metrics = PromptContractProbeMetrics(
        total=len(PROMPT_CONTRACT_PROBE_CASES),
        strict_json_count=strict_count,
        host_owned_deviation_count=host_deviations,
        candidate_deviation_count=candidate_deviations,
        claims_nonempty_count=claims_nonempty,
        public_steps_count=public_steps,
        final_answer_count=final_answers,
        method_family_match_count=method_matches,
        private_reasoning_field_count=private_fields,
    )
    return PromptContractProbeReport(
        metrics=metrics,
        records=records,
        acceptance_errors=_acceptance_errors(metrics),
    )


def _acceptance_errors(metrics: PromptContractProbeMetrics) -> list[str]:
    values = metrics.to_dict()
    checks = (
        ("strict_json_rate", 0.95, "minimum"),
        ("candidate_deviation_rate", 0.05, "maximum"),
        ("claims_nonempty_rate", 0.90, "minimum"),
        ("public_steps_rate", 0.95, "minimum"),
        ("final_answer_rate", 0.95, "minimum"),
        ("method_family_match_rate", 0.90, "minimum"),
    )
    errors: list[str] = []
    for name, threshold, direction in checks:
        actual = float(values[name])
        if direction == "minimum" and actual < threshold:
            errors.append(f"{name} below {threshold:.2f}: {actual:.4f}")
        if direction == "maximum" and actual > threshold:
            errors.append(f"{name} above {threshold:.2f}: {actual:.4f}")
    if metrics.host_owned_deviation_count:
        errors.append(
            "host_owned_deviation_count must be zero: "
            f"{metrics.host_owned_deviation_count}"
        )
    if metrics.private_reasoning_field_count:
        errors.append(
            "private_reasoning_field_count must be zero: "
            f"{metrics.private_reasoning_field_count}"
        )
    return errors


def _contains_private_reasoning_field(response: str) -> bool:
    try:
        payload = json.loads(response)
    except (json.JSONDecodeError, TypeError):
        return False
    forbidden = {
        "chain_of_thought",
        "hidden_reasoning",
        "private_reasoning",
        "private_scratchpad",
        "scratchpad",
    }

    def visit(value: object) -> bool:
        if isinstance(value, dict):
            return any(
                str(key).strip().lower() in forbidden or visit(item)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return any(visit(item) for item in value)
        return False

    return visit(payload)
