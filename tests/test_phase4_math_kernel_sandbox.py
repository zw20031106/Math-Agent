from __future__ import annotations

import json
from io import BytesIO
from subprocess import CompletedProcess
from types import SimpleNamespace

import pytest

from mathforge.math_ir.expression import build_expression_ir
from mathforge.tools.executor import ToolExecutor
from mathforge.tools.linear_algebra import matrix_shape_check
from mathforge.tools.numerical import (
    _sample_pool,
    density_normalization,
    numerical_residual,
    small_case_enumeration,
)
from mathforge.tools.registry import ToolRegistry
from mathforge.tools.resource_limits import (
    ExpressionLimitError,
    inspect_expression,
)
from mathforge.tools.symbolic import symbolic_equivalence
from mathforge.tools import worker
from mathforge.config import HarnessConfig
from mathforge.harness.terminalizer import (
    NoThrowTerminalizer,
    minimal_fallback_result,
)
from tests.fake_client import FakeClient
from user_agent import ReasoningAgent


def test_expression_ir_preserves_source_domain_and_singularities():
    ir = build_expression_ir(
        "(x**2-1)/(x-1)",
        domains={"x": "real"},
    )

    assert ir.source_text == "(x**2-1)/(x-1)"
    assert ir.normalized_source == "(x**2-1)/(x-1)"
    assert ir.ast is not None
    assert str(ir.sympy_expression) == "(x**2 - 1)/(x - 1)"
    assert ir.symbols == ("x",)
    assert ir.explicit_domains == {"x": "real"}
    assert any("x - 1" in item for item in ir.singularities)
    assert any("!= 0" in item for item in ir.derived_domain_constraints)
    assert ir.context_complete is True


@pytest.mark.parametrize(
    ("left", "right", "assumptions", "domains", "expected"),
    [
        (
            "(x**2-1)/(x-1)",
            "x+1",
            [],
            {"x": "real"},
            "unknown",
        ),
        ("sqrt(x**2)", "x", ["x >= 0"], {"x": "real"}, "pass"),
        ("log(x**2)", "2*log(x)", ["x > 0"], {"x": "real"}, "pass"),
        (
            "(x**(1/2))**2",
            "x",
            ["x >= 0"],
            {"x": "real"},
            "pass",
        ),
        ("sqrt(x**2)", "x", [], {"x": "complex"}, "unknown"),
        ("x", "1", [], {"x": "natural"}, "unknown"),
    ],
)
def test_symbolic_equivalence_respects_domains_and_conditions(
    left,
    right,
    assumptions,
    domains,
    expected,
):
    result = ToolExecutor().execute(
        "symbolic_equivalence",
        {
            "left": left,
            "right": right,
            "assumptions": assumptions,
            "domains": domains,
        },
    )

    assert result.status == expected
    if expected == "pass":
        assert result.strength == "hard"
        assert result.payload["context_complete"] is True
    else:
        assert not (
            result.status == "pass"
            and result.strength == "hard"
            and result.payload.get("context_complete") is True
        )


def test_numerical_residual_uses_independent_domain_aware_samples():
    unequal = ToolExecutor().execute(
        "numerical_residual",
        {
            "left": "x",
            "right": "y",
            "domains": {"x": "real", "y": "real"},
        },
    )
    equal = ToolExecutor().execute(
        "numerical_residual",
        {
            "left": "x+y",
            "right": "y+x",
            "domains": {"x": "integer", "y": "integer"},
        },
    )

    assert unequal.status == "fail"
    assert equal.status == "pass"
    assert unequal.strength == equal.strength == "medium"
    assert unequal.payload["symbol_count"] == 2
    assert unequal.payload["attempted_samples"] >= 1
    assert unequal.payload["valid_samples"] >= 1
    assert unequal.payload["sample_strategy"] == "deterministic_independent_product"
    assert (
        unequal.payload["attempted_samples"]
        == unequal.payload["valid_samples"]
        + unequal.payload["rejected_samples"]
    )


@pytest.mark.parametrize(
    ("expression", "reason"),
    [
        ("9" * 257, "integer_digits"),
        ("9**257", "exponent"),
        ("(" * 70 + "x" + ")" * 70, "depth"),
        ("+".join(["x"] * 600), "nodes"),
    ],
)
def test_expression_resource_preflight_rejects_adversarial_inputs(
    expression,
    reason,
):
    with pytest.raises(ExpressionLimitError, match=reason):
        inspect_expression(expression)


def test_every_sympy_backed_tool_is_isolated():
    registry = ToolRegistry()
    for name in (
        "safe_parse_expression",
        "symbolic_equivalence",
        "simplify_expression",
        "numerical_residual",
        "density_normalization",
        "small_case_enumeration",
    ):
        assert registry.get(name).isolated is True


def test_oversized_or_malformed_worker_response_fails_closed(monkeypatch):
    def oversized(*args, **kwargs):
        del args, kwargs
        return CompletedProcess([], 0, stdout="x" * 1_100_000, stderr="")

    monkeypatch.setattr("mathforge.tools.executor.subprocess.run", oversized)
    oversized_result = ToolExecutor().execute(
        "simplify_expression",
        {"expression": "x+1"},
    )

    def malformed(*args, **kwargs):
        del args, kwargs
        return CompletedProcess([], 0, stdout="{", stderr="")

    monkeypatch.setattr("mathforge.tools.executor.subprocess.run", malformed)
    malformed_result = ToolExecutor().execute(
        "simplify_expression",
        {"expression": "x+1"},
    )

    assert oversized_result.status == "error"
    assert oversized_result.summary == "isolated tool response exceeded limit"
    assert malformed_result.status == "error"
    assert malformed_result.summary == "invalid isolated tool response"


def test_worker_failure_payload_is_small_structured_json():
    result = ToolExecutor().execute(
        "safe_parse_expression",
        {"expression": "Piecewise((1, x > 0), (0, True))"},
    )

    serialized = json.dumps(result.to_dict(), ensure_ascii=False)
    assert result.status == "error"
    assert len(serialized.encode("utf-8")) < 4096
    assert "Traceback" not in serialized


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("(x+1)**2", "x**2+2*x+1"),
        ("(x+1)*(x-1)", "x**2-1"),
        ("x+y", "y+x"),
        ("(x+y)+z", "x+(y+z)"),
        ("a+a", "2*a"),
    ],
)
def test_symbolic_metamorphic_equivalent_transformations(left, right):
    result = symbolic_equivalence(left=left, right=right)

    assert result["status"] == "pass"
    assert result["strength"] == "hard"


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("x", "x+1"),
        ("x", "-x"),
        ("x+y", "x-y"),
    ],
)
def test_symbolic_metamorphic_non_equivalent_perturbations(left, right):
    result = symbolic_equivalence(left=left, right=right)

    assert result["status"] == "fail"
    assert result["strength"] == "hard"


def test_numerical_variable_permutation_and_undecidable_density():
    residual = numerical_residual(
        left="x+y",
        right="y+x",
        domains={"x": "rational", "y": "integer"},
    )
    density = density_normalization(
        expression="sin(x**x)",
        variable="x",
        lower="0",
        upper="1",
    )
    matrix = matrix_shape_check(matrix=[[1, 2], [3]])

    assert residual["status"] == "pass"
    assert residual["strength"] == "medium"
    assert density["status"] == "unknown"
    assert matrix["status"] == "fail"


def test_worker_main_emits_only_bounded_structured_protocol(monkeypatch):
    def invoke(payload: bytes) -> dict:
        output = BytesIO()
        monkeypatch.setattr(
            worker.sys,
            "stdin",
            SimpleNamespace(buffer=BytesIO(payload)),
        )
        monkeypatch.setattr(
            worker.sys,
            "stdout",
            SimpleNamespace(buffer=output),
        )
        assert worker.main(apply_limits=False) == 0
        return json.loads(output.getvalue())

    success = invoke(
        json.dumps(
            {
                "name": "safe_parse_expression",
                "arguments": {"expression": "x+1"},
            }
        ).encode("utf-8")
    )
    direct_rejected = invoke(
        json.dumps(
            {
                "name": "answer_type_check",
                "arguments": {"answer": "2", "answer_type": "integer"},
            }
        ).encode("utf-8")
    )
    malformed = invoke(b"{")
    oversized = invoke(b"x" * 40_000)

    assert success["status"] == "pass"
    assert direct_rejected["status"] == "error"
    assert malformed["status"] == "error"
    assert oversized["summary"] == "isolated tool request exceeded limit"


def test_worker_write_replaces_oversized_payload(monkeypatch):
    output = BytesIO()
    monkeypatch.setattr(
        worker.sys,
        "stdout",
        SimpleNamespace(buffer=output),
    )

    assert worker._write({"value": "x" * 1_100_000}) == 0
    payload = json.loads(output.getvalue())

    assert payload["status"] == "error"
    assert payload["summary"] == "isolated tool response exceeded limit"


def test_numerical_resource_and_domain_branches_fail_closed(monkeypatch):
    original_n = __import__("sympy").N

    def fail_n(*args, **kwargs):
        del args, kwargs
        raise OverflowError

    monkeypatch.setattr("mathforge.tools.numerical.sympy.N", fail_n)
    rejected = numerical_residual(left="x", right="0")
    monkeypatch.setattr("mathforge.tools.numerical.sympy.N", original_n)

    assert rejected["status"] == "unknown"
    assert rejected["payload"]["rejected_samples"] > 0
    assert density_normalization(
        expression="2",
        variable="x",
        lower="0",
        upper="1",
    )["status"] == "fail"
    assert small_case_enumeration(
        expression="x",
        variable="x",
        values=[10**300],
    )["status"] == "unknown"
    assert _sample_pool(None, [0.25, 0.5])
    for domain in (
        "integer",
        "rational",
        "natural_positive",
        "natural",
        "natural_zero",
        "complex",
        "real",
    ):
        assert _sample_pool(domain, None)


def test_formal_entry_and_terminalizer_coverage_boundaries():
    with pytest.raises(TypeError, match="HarnessConfig"):
        ReasoningAgent(FakeClient(), config=object())

    agent = ReasoningAgent(FakeClient(), config=HarnessConfig())

    class RaisingHarness:
        @staticmethod
        def solve(problem, metadata):
            del problem, metadata
            raise RuntimeError("private")

    agent._harness = RaisingHarness()
    fallback = agent.solve("x", {"id": "formal-fallback"})
    assert fallback["id"] == "formal-fallback"
    assert fallback["status"] == "failed"

    terminalizer = NoThrowTerminalizer()
    result = terminalizer.build_result(
        final_response="",
        trace_factory=lambda: [{"event": "run_completed"}],
        metrics_factory=lambda: "invalid",  # type: ignore[arg-type,return-value]
        provenance="invalid",  # type: ignore[arg-type]
    )
    minimal = minimal_fallback_result()

    assert result["final_response"]
    assert result["run_metrics"]["fallback_used"] is True
    assert result["provenance"] == {}
    assert minimal["trace"][-1]["event"] == "run_completed"


@pytest.mark.parametrize(
    ("values", "expected_status"),
    [
        ([], "unknown"),
        ([0], "pass"),
        (list(range(128)), "fail"),
        (list(range(129)), "unknown"),
    ],
)
def test_finite_enumeration_boundaries_remain_fail_closed(
    values,
    expected_status,
):
    result = ToolExecutor().execute(
        "small_case_enumeration",
        {
            "expression": "x",
            "variable": "x",
            "values": values,
            "expected": "0",
        },
    )

    assert result.status == expected_status
