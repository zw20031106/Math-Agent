# Tool capability boundaries

| Tool | Can establish | Cannot establish |
|---|---|---|
| `safe_parse_expression` | Input belongs to the restricted arithmetic grammar | Mathematical truth |
| `symbolic_equivalence` | Exact simplified equality or a concrete exact counterexample | Equality outside parsed domains and assumptions |
| `simplify_expression` | Exact simplification of a parsed expression | Applicability of external theorem conditions |
| `numerical_residual` | Residual size at deterministic finite samples | Universal equality |
| `matrix_shape_check` | Rectangularity and dimensions | Matrix identity or invertibility |
| `density_normalization` | Exact integral equals one | Nonnegativity of the density |
| `small_case_enumeration` | Truth or a counterexample in supplied finite cases | Untested cases |
| `latex_syntax_check` | Brace balance | Valid or correct mathematics |
| `answer_type_check` | Basic output-shape conformance | Correctness of the answer |

Timeouts are `unknown`, never pass or fail. Tool errors are isolated from the solving path.
