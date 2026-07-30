from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable


_CLAIM_PROMPT_EXAMPLES: dict[str, dict[str, Any]] = {
    "safe_parse_expression": {
        "claim": {
            "statement": "The expression x**2+1 uses the restricted arithmetic grammar.",
            "check_type": "safe_parse_expression",
        },
        "invalid_claim": "The expression is fine.",
    },
    "symbolic_equivalence": {
        "claim": {
            "statement": "(x+1)**2 equals x**2+2*x+1 for real x.",
            "check_type": "symbolic_equivalence",
        },
        "invalid_claim": "These forms look equivalent.",
    },
    "simplify_expression": {
        "claim": {
            "statement": "The expression x+x simplifies to 2*x.",
            "check_type": "simplify_expression",
        },
        "invalid_claim": "Simplify the previous expression.",
    },
    "numerical_residual": {
        "claim": {
            "statement": "x**2 and x*x have zero residual at the stated samples.",
            "check_type": "numerical_residual",
        },
        "invalid_claim": "The numerical result seems close.",
    },
    "matrix_shape_check": {
        "claim": {
            "statement": "The matrix [[1,0],[0,1]] has shape 2 by 2.",
            "check_type": "matrix_shape_check",
        },
        "invalid_claim": "The matrix dimensions are suitable.",
    },
    "density_normalization": {
        "claim": {
            "statement": "The density 1/2 on [0,2] integrates to one.",
            "check_type": "density_normalization",
        },
        "invalid_claim": "This is a valid density.",
    },
    "small_case_enumeration": {
        "claim": {
            "statement": "n-n equals zero for n in {0,1,2,3}.",
            "check_type": "small_case_enumeration",
        },
        "invalid_claim": "The first few cases work.",
    },
    "latex_syntax_check": {
        "claim": {
            "statement": "The public expression \\frac{1}{2} has balanced braces.",
            "check_type": "latex_syntax_check",
        },
        "invalid_claim": "The notation is valid mathematics.",
    },
    "answer_type_check": {
        "claim": {
            "statement": "The final answer 2 has the requested integer shape.",
            "check_type": "answer_type_check",
        },
        "invalid_claim": "The final answer is correct.",
    },
}


def claim_prompt_examples(
    names: Iterable[str],
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Generate examples through the production Host CheckSpec builder."""

    if limit < 0:
        raise ValueError("tool prompt example limit must be nonnegative")
    from mathforge.harness.schemas import CandidateSolution, Claim
    from mathforge.tools.executor import ToolExecutor
    from mathforge.verification.tool_requests import ClaimToolRequestBuilder

    tools = ToolExecutor(use_mcp=False)
    builder = ClaimToolRequestBuilder(tools)
    selected_tools = list(tools.claimable_tools)
    examples: list[dict[str, Any]] = []
    for name in dict.fromkeys(names):
        template = _CLAIM_PROMPT_EXAMPLES.get(name)
        if template is None:
            continue
        claim_payload = template["claim"]
        claim = Claim(
            "c1",
            str(claim_payload["statement"]),
            check_type=str(claim_payload["check_type"]),
        )
        candidate = CandidateSolution(
            "prompt-example",
            "PrimarySolver",
            "schema-example",
            "2",
            "integer",
            claims=[claim],
        )
        request = builder.build(
            candidate,
            claim,
            domains={"x": "R"},
            selected_tools=selected_tools,
        )
        if not request.schema_valid:
            raise ValueError(f"tool prompt example is not constructible: {name}")
        examples.append(
            {
                "tool": name,
                **deepcopy(template),
                "host_arguments": dict(request.arguments),
                "check_spec": claim.check_spec.to_dict(),
            }
        )
        if len(examples) >= limit:
            break
    return examples
