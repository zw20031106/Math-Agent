from __future__ import annotations

import json

from mathforge.tools.executor import ToolExecutor
from mathforge.tools.registry import ToolRegistry


def test_all_first_batch_tools_are_registered():
    assert ToolRegistry().names() == sorted(
        [
            "safe_parse_expression",
            "symbolic_equivalence",
            "simplify_expression",
            "numerical_residual",
            "matrix_shape_check",
            "density_normalization",
            "small_case_enumeration",
            "latex_syntax_check",
            "answer_type_check",
        ]
    )


def test_symbolic_equivalence_passes_and_non_equivalence_hard_fails():
    executor = ToolExecutor()
    equivalent = executor.execute("symbolic_equivalence", {"left": "(x+1)^2", "right": "x^2+2*x+1"})
    assert equivalent.status == "pass"
    assert equivalent.strength == "hard"
    unequal = executor.execute("symbolic_equivalence", {"left": "x", "right": "x+1"})
    assert unequal.status == "fail"
    assert unequal.strength == "hard"


def test_safe_parser_rejects_code_execution_syntax():
    result = ToolExecutor().execute(
        "safe_parse_expression",
        {"expression": "__import__('os').system('echo unsafe')"},
    )
    assert result.status == "error"


def test_matrix_and_answer_checks_are_json_serializable():
    executor = ToolExecutor()
    matrix = executor.execute("matrix_shape_check", {"matrix": [[1, 2], [3, 4]]})
    answer = executor.execute("answer_type_check", {"answer": "A", "answer_type": "choice"})
    assert matrix.status == answer.status == "pass"
    json.dumps([matrix.to_dict(), answer.to_dict()])


def test_isolated_timeout_is_unknown():
    result = ToolExecutor(default_timeout=0.0001).execute(
        "simplify_expression",
        {"expression": "(x+1)^20"},
    )
    assert result.status == "unknown"


def test_symbolic_counterexamples_respect_assumptions_and_domains():
    executor = ToolExecutor()
    constrained = executor.execute(
        "symbolic_equivalence",
        {
            "left": "sqrt(x^2)",
            "right": "x",
            "assumptions": ["x >= 0"],
            "domains": {"x": "R"},
        },
    )
    negative_domain = executor.execute(
        "symbolic_equivalence",
        {
            "left": "sqrt(x^2)",
            "right": "x",
            "assumptions": ["x < 0"],
            "domains": {"x": "R"},
        },
    )
    unparsed = executor.execute(
        "symbolic_equivalence",
        {
            "left": "x",
            "right": "x+1",
            "assumptions": ["x is sufficiently nice"],
        },
    )
    assert constrained.status == "unknown"
    assert constrained.strength == "medium"
    assert negative_domain.status == "fail"
    assert negative_domain.strength == "hard"
    assert unparsed.status == "unknown"


def test_tool_version_round_trips_in_result_schema():
    result = ToolExecutor().execute(
        "answer_type_check", {"answer": "2", "answer_type": "integer"}
    )
    assert result.tool_version == "1"
    assert result.to_dict()["tool_version"] == "1"
    assert result.capability == "answer.shape"
    assert result.to_dict()["claim_state"] == "unknown"


def test_symbolic_counterexample_search_uses_independent_symbol_values():
    result = ToolExecutor().execute(
        "symbolic_equivalence",
        {"left": "x-y", "right": "0"},
    )
    assert result.status == "fail"
    assert result.payload["counterexample"]["x"] != result.payload["counterexample"]["y"]
