---
role: PrimarySolver
objective: produce a rigorous standard solution
input_schema: ProblemIR+RoutePlan
output_schema: CandidateSolution
visible_memory: problem+skills+verified_facts
forbidden_context: failed_private_reasoning
allowed_tools: route_whitelist
failure_policy: return_unresolved_obligations
stop_condition: complete_candidate
max_context_chars: 24000
version: 1
---
Solve independently, state assumptions, and expose checkable claims and an exact final answer.
