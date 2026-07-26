from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable


_CLAIM_PROMPT_EXAMPLES: dict[str, dict[str, Any]] = {
    "safe_parse_expression": {
        "claim": {
            "statement": "The expression x**2+1 uses the restricted arithmetic grammar.",
            "check_type": "safe_parse_expression",
        },
        "host_arguments": {"expression": "x**2+1"},
        "invalid_claim": "The expression is fine.",
    },
    "symbolic_equivalence": {
        "claim": {
            "statement": "(x+1)**2 equals x**2+2*x+1 for real x.",
            "check_type": "symbolic_equivalence",
        },
        "host_arguments": {
            "left": "(x+1)**2",
            "right": "x**2+2*x+1",
            "assumptions": [],
            "domains": {"x": "R"},
        },
        "invalid_claim": "These forms look equivalent.",
    },
    "simplify_expression": {
        "claim": {
            "statement": "The expression x+x simplifies to 2*x.",
            "check_type": "simplify_expression",
        },
        "host_arguments": {"expression": "x+x"},
        "invalid_claim": "Simplify the previous expression.",
    },
    "numerical_residual": {
        "claim": {
            "statement": "x**2 and x*x have zero residual at the stated samples.",
            "check_type": "numerical_residual",
        },
        "host_arguments": {
            "left": "x**2",
            "right": "x*x",
            "tolerance": 1e-09,
            "samples": [-1, 0, 2],
        },
        "invalid_claim": "The numerical result seems close.",
    },
    "matrix_shape_check": {
        "claim": {
            "statement": "The matrix [[1,0],[0,1]] has shape 2 by 2.",
            "check_type": "matrix_shape_check",
        },
        "host_arguments": {"matrix": [[1, 0], [0, 1]]},
        "invalid_claim": "The matrix dimensions are suitable.",
    },
    "density_normalization": {
        "claim": {
            "statement": "The density 1/2 on [0,2] integrates to one.",
            "check_type": "density_normalization",
        },
        "host_arguments": {
            "expression": "1/2",
            "variable": "x",
            "lower": "0",
            "upper": "2",
        },
        "invalid_claim": "This is a valid density.",
    },
    "small_case_enumeration": {
        "claim": {
            "statement": "n-n equals zero for n in {0,1,2,3}.",
            "check_type": "small_case_enumeration",
        },
        "host_arguments": {
            "expression": "n-n",
            "variable": "n",
            "values": [0, 1, 2, 3],
            "expected": "0",
        },
        "invalid_claim": "The first few cases work.",
    },
    "latex_syntax_check": {
        "claim": {
            "statement": "The public expression \\frac{1}{2} has balanced braces.",
            "check_type": "latex_syntax_check",
        },
        "host_arguments": {"text": "\\frac{1}{2}"},
        "invalid_claim": "The notation is valid mathematics.",
    },
    "answer_type_check": {
        "claim": {
            "statement": "The final answer 2 has the requested integer shape.",
            "check_type": "answer_type_check",
        },
        "host_arguments": {"answer": "2", "answer_type": "integer"},
        "invalid_claim": "The final answer is correct.",
    },
}


def claim_prompt_examples(
    names: Iterable[str],
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    if limit < 0:
        raise ValueError("tool prompt example limit must be nonnegative")
    examples: list[dict[str, Any]] = []
    for name in dict.fromkeys(names):
        example = _CLAIM_PROMPT_EXAMPLES.get(name)
        if example is None:
            continue
        examples.append({"tool": name, **deepcopy(example)})
        if len(examples) >= limit:
            break
    return examples
