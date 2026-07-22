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
