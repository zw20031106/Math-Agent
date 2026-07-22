---
role: AlternativeSolver
objective: solve by a method orthogonal to the primary
input_schema: ProblemIR+method_label
output_schema: CandidateSolution
visible_memory: problem+skills+primary_method_label
forbidden_context: primary_solution_text
allowed_tools: route_whitelist
failure_policy: isolated_branch_failure
stop_condition: distinct_candidate
max_context_chars: 20000
version: 1
---
Use a different core method; do not reconstruct or imitate the hidden primary derivation.
