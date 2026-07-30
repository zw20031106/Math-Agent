from __future__ import annotations

import ast
from dataclasses import dataclass
import re
from time import perf_counter
from typing import Callable, TYPE_CHECKING

import sympy

from mathforge.harness.schemas import (
    CandidateSolution,
    CandidateSource,
    Claim,
    MethodStep,
    ProblemIR,
)
from mathforge.math_ir.expression import build_expression_ir
from mathforge.verification.capabilities import (
    ClaimVerificationState,
    VerificationCapability,
)

if TYPE_CHECKING:
    from mathforge.tools.registry import ToolResult


@dataclass(frozen=True)
class ShadowOutcome:
    status: str
    capability: str
    normalized_input: str
    final_answer: str = ""
    public_solution_steps: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    elapsed_seconds: float = 0.0

    @property
    def exact(self) -> bool:
        return self.status == "exact" and bool(self.final_answer.strip())

    def to_candidate(self, answer_type: str) -> CandidateSolution | None:
        if not self.exact:
            return None
        claim = Claim(
            "shadow-c1",
            f"Deterministic capability {self.capability} returns "
            f"{self.final_answer}.",
            check_type="symbolic_equivalence",
            importance="critical",
            claim_kind="equality",
            verification_state="semantically_verified",
        )
        candidate = CandidateSolution(
            candidate_id="shadow-1",
            role="DeterministicShadow",
            method="deterministic-shadow",
            final_answer=self.final_answer,
            answer_type=answer_type,
            assumptions=list(self.assumptions),
            claims=[claim],
            public_solution_steps=list(self.public_solution_steps),
            solution_text="\n".join(self.public_solution_steps),
            parse_status="deterministic_exact",
            method_steps=[
                MethodStep(
                    "shadow-s1",
                    "computation",
                    ["shadow-c1"],
                    "",
                )
            ],
            source=CandidateSource.DETERMINISTIC_SHADOW.value,
            parse_tier="strict",
        )
        candidate.validate()
        return candidate

    def to_tool_result(self) -> ToolResult:
        from mathforge.tools.registry import ToolResult

        return ToolResult(
            tool_name="deterministic_shadow",
            status="pass" if self.exact else "unknown",
            strength="hard" if self.exact else "soft",
            summary=(
                "deterministic shadow capability completed exactly"
                if self.exact
                else "deterministic shadow capability was unavailable"
            ),
            payload={
                "status": self.status,
                "capability": self.capability,
                "normalized_input": self.normalized_input,
                "final_answer": self.final_answer,
                "assumptions": list(self.assumptions),
                "limitations": list(self.limitations),
            },
            tool_version="1",
            capability=(
                VerificationCapability.EQUALITY_SYMBOLIC_UNDER_DOMAIN.value
                if self.exact
                else VerificationCapability.NONE.value
            ),
            claim_state=(
                ClaimVerificationState.SEMANTICALLY_VERIFIED.value
                if self.exact
                else ClaimVerificationState.UNKNOWN.value
            ),
        )

    @classmethod
    def from_dict(cls, payload: dict) -> "ShadowOutcome":
        if not isinstance(payload, dict):
            raise ValueError("shadow outcome must be an object")
        status = str(payload.get("status", ""))
        if status not in {"exact", "verified_numeric", "partial", "unsupported", "failed"}:
            raise ValueError("shadow outcome status is invalid")
        list_fields = {}
        for name in ("public_solution_steps", "assumptions", "limitations"):
            value = payload.get(name, [])
            if not isinstance(value, list) or any(
                not isinstance(item, str) for item in value
            ):
                raise ValueError(f"shadow outcome {name} must be a string list")
            list_fields[name] = tuple(value)
        return cls(
            status=status,
            capability=str(payload.get("capability", "")),
            normalized_input=str(payload.get("normalized_input", "")),
            final_answer=str(payload.get("final_answer", "")),
            public_solution_steps=list_fields["public_solution_steps"],
            assumptions=list_fields["assumptions"],
            limitations=list_fields["limitations"],
            elapsed_seconds=float(payload.get("elapsed_seconds", 0.0)),
        )

    def to_trace_dict(self, *, include_answer: bool) -> dict:
        return {
            "status": self.status,
            "capability": self.capability,
            "normalized_input": self.normalized_input,
            "final_answer": self.final_answer if include_answer else "",
            "public_solution_steps": (
                list(self.public_solution_steps) if include_answer else []
            ),
            "assumptions": list(self.assumptions),
            "limitations": list(self.limitations),
            "elapsed_seconds": self.elapsed_seconds,
        }


class ShadowCapabilityRegistry:
    def __init__(self) -> None:
        self._handlers: tuple[
            tuple[str, Callable[[str], tuple[str, list[str], list[str]] | None]],
            ...,
        ] = (
            ("matrix_exact", _solve_matrix),
            ("limit_exact", _solve_limit),
            ("integral_exact", _solve_integral),
            ("finite_or_symbolic_sum", _solve_sum),
            ("algebraic_system", _solve_system),
            ("single_equation", _solve_equation),
            ("restricted_expression", _solve_expression),
        )

    def names(self) -> list[str]:
        return [name for name, _ in self._handlers]

    def solve(
        self,
        problem: ProblemIR,
        *,
        time_budget_seconds: float = 5.0,
    ) -> ShadowOutcome:
        started = perf_counter()
        text = problem.normalized_problem.strip()
        if not text or len(text) > 4096:
            return ShadowOutcome(
                "unsupported",
                "",
                "",
                limitations=("problem_shape_unsupported",),
                elapsed_seconds=round(perf_counter() - started, 6),
            )
        for capability, handler in self._handlers:
            if perf_counter() - started >= time_budget_seconds:
                return ShadowOutcome(
                    "failed",
                    capability,
                    "",
                    limitations=("shadow_time_budget_exhausted",),
                    elapsed_seconds=round(perf_counter() - started, 6),
                )
            try:
                result = handler(text)
            except (ArithmeticError, SyntaxError, TypeError, ValueError):
                continue
            except Exception:
                continue
            if result is None:
                continue
            answer, steps, assumptions = result
            return ShadowOutcome(
                "exact",
                capability,
                text,
                final_answer=answer,
                public_solution_steps=tuple(steps),
                assumptions=tuple(assumptions),
                limitations=(
                    "exact only for the normalized operation shown",
                ),
                elapsed_seconds=round(perf_counter() - started, 6),
            )
        return ShadowOutcome(
            "unsupported",
            "",
            text,
            limitations=("no_allowlisted_capability_match",),
            elapsed_seconds=round(perf_counter() - started, 6),
        )


def run_shadow_probe(
    *,
    problem_ir: dict,
    time_budget_seconds: float = 5.0,
) -> dict:
    outcome = ShadowCapabilityRegistry().solve(
        ProblemIR.from_dict(problem_ir),
        time_budget_seconds=max(0.1, min(5.0, float(time_budget_seconds))),
    )
    return {
        "status": "pass" if outcome.exact else "unknown",
        "strength": "hard" if outcome.exact else "soft",
        "summary": (
            "deterministic shadow probe completed"
            if outcome.exact
            else "deterministic shadow probe unsupported"
        ),
        "payload": {
            "outcome": outcome.to_trace_dict(include_answer=True),
        },
    }


def _expression(source: str) -> sympy.Expr:
    return build_expression_ir(source).sympy_expression


def _answer(value) -> str:
    return str(sympy.simplify(value))


def _solve_expression(text: str):
    match = re.search(
        r"(?:compute|calculate|evaluate)\s+(.+?)[.?\s]*$",
        text,
        re.IGNORECASE,
    )
    if match is None:
        return None
    source = match.group(1).strip().rstrip(".?")
    value = _expression(source)
    if value.free_symbols:
        return None
    return (
        _answer(value),
        [f"Evaluate the restricted expression {source} exactly."],
        [],
    )


def _solve_equation(text: str):
    match = re.search(
        r"solve\s+(.+?)\s*=\s*(.+?)(?:\s+for\s+([A-Za-z]\w*))?[.?\s]*$",
        text,
        re.IGNORECASE,
    )
    if match is None:
        return None
    left = _expression(match.group(1))
    right = _expression(match.group(2).rstrip(".?"))
    symbols = sorted(left.free_symbols | right.free_symbols, key=str)
    if match.group(3):
        variable = sympy.Symbol(match.group(3))
    elif len(symbols) == 1:
        variable = symbols[0]
    else:
        return None
    solutions = sympy.solve(sympy.Eq(left, right), variable)
    if not solutions:
        return None
    answer = (
        _answer(solutions[0])
        if len(solutions) == 1
        else "{" + ", ".join(_answer(item) for item in solutions) + "}"
    )
    return (
        answer,
        [
            f"Form the exact equation {left} = {right}.",
            f"Solve it for {variable}.",
        ],
        [],
    )


def _solve_system(text: str):
    match = re.search(
        r"solve\s+(?:the\s+)?system\s+(.+?)\s+for\s+"
        r"([A-Za-z]\w*(?:\s*,\s*[A-Za-z]\w*)+)[.?\s]*$",
        text,
        re.IGNORECASE,
    )
    if match is None:
        return None
    equation_sources = [
        item.strip()
        for item in re.split(r"\s*;\s*|\s*,\s*(?=[A-Za-z]\w*\s*[+\-=])", match.group(1))
        if item.strip()
    ]
    if len(equation_sources) < 2:
        return None
    equations = []
    for source in equation_sources:
        if "=" not in source:
            return None
        left, right = source.split("=", 1)
        equations.append(sympy.Eq(_expression(left), _expression(right)))
    variables = [
        sympy.Symbol(item.strip())
        for item in match.group(2).split(",")
    ]
    solutions = sympy.solve(equations, variables, dict=True)
    if not solutions:
        return None
    rendered = []
    for solution in solutions:
        rendered.append(
            "("
            + ", ".join(_answer(solution[variable]) for variable in variables)
            + ")"
        )
    return (
        rendered[0] if len(rendered) == 1 else "{" + ", ".join(rendered) + "}",
        [
            "Reconstruct each equation using the restricted expression parser.",
            "Solve the exact system for the requested variables.",
        ],
        [],
    )


def _solve_matrix(text: str):
    matrix_match = re.search(r"(\[\s*\[.*?\]\s*\])", text, re.DOTALL)
    if matrix_match is None:
        return None
    raw = ast.literal_eval(matrix_match.group(1))
    matrix = sympy.Matrix(raw)
    lowered = text.lower()
    if "determinant" in lowered or re.search(r"\bdet\b", lowered):
        value = matrix.det()
        operation = "determinant"
    elif "rank" in lowered:
        value = matrix.rank()
        operation = "rank"
    elif "eigenvalue" in lowered:
        values = sorted(matrix.eigenvals(), key=str)
        value = sympy.FiniteSet(*values)
        operation = "eigenvalues"
    else:
        return None
    return (
        _answer(value),
        [f"Construct the exact matrix and compute its {operation}."],
        [],
    )


def _solve_limit(text: str):
    match = re.search(
        r"limit(?:\s+of)?\s+(.+?)\s+as\s+([A-Za-z]\w*)\s*"
        r"(?:->|approaches)\s*(.+?)[.?\s]*$",
        text,
        re.IGNORECASE,
    )
    if match is None:
        return None
    expression = _expression(match.group(1))
    variable = sympy.Symbol(match.group(2))
    point = _expression(match.group(3).rstrip(".?"))
    value = sympy.limit(expression, variable, point)
    if isinstance(value, sympy.Limit):
        return None
    return (
        _answer(value),
        [f"Evaluate the exact limit of {expression} as {variable} approaches {point}."],
        [],
    )


def _solve_integral(text: str):
    match = re.search(
        r"integral(?:\s+of)?\s+(.+?)\s+from\s+(.+?)\s+to\s+"
        r"(.+?)(?:\s+with\s+respect\s+to\s+([A-Za-z]\w*))?[.?\s]*$",
        text,
        re.IGNORECASE,
    )
    if match is not None:
        expression = _expression(match.group(1))
        lower = _expression(match.group(2))
        upper = _expression(match.group(3).rstrip(".?"))
        symbols = sorted(expression.free_symbols, key=str)
        variable = (
            sympy.Symbol(match.group(4))
            if match.group(4)
            else symbols[0] if len(symbols) == 1 else None
        )
        if variable is None:
            return None
        value = sympy.integrate(expression, (variable, lower, upper))
        step = (
            f"Integrate {expression} over [{lower}, {upper}] "
            f"with respect to {variable}."
        )
    else:
        indefinite = re.search(
            r"(?:indefinite\s+)?integral(?:\s+of)?\s+(.+?)\s+"
            r"with\s+respect\s+to\s+([A-Za-z]\w*)[.?\s]*$",
            text,
            re.IGNORECASE,
        )
        if indefinite is None:
            return None
        expression = _expression(indefinite.group(1))
        variable = sympy.Symbol(indefinite.group(2))
        value = sympy.integrate(expression, variable)
        step = f"Find an antiderivative of {expression} with respect to {variable}."
    if isinstance(value, sympy.Integral):
        return None
    return (
        f"{_answer(value)} + C" if match is None else _answer(value),
        [step],
        [],
    )


def _solve_sum(text: str):
    match = re.search(
        r"sum(?:\s+of)?\s+(.+?)\s+for\s+([A-Za-z]\w*)\s+from\s+"
        r"(.+?)\s+to\s+(.+?)[.?\s]*$",
        text,
        re.IGNORECASE,
    )
    if match is None:
        return None
    expression = _expression(match.group(1))
    variable = sympy.Symbol(match.group(2))
    lower = _expression(match.group(3))
    upper_source = match.group(4).rstrip(".?").strip().casefold()
    upper = (
        sympy.oo
        if upper_source in {"infinity", "inf", "oo"}
        else _expression(upper_source)
    )
    value = sympy.summation(expression, (variable, lower, upper))
    if isinstance(value, sympy.Sum):
        return None
    return (
        _answer(value),
        [f"Evaluate the exact sum of {expression} for {variable} from {lower} to {upper}."],
        [],
    )
