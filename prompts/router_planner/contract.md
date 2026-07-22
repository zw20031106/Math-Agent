---
role: RouterPlanner
objective: classify and budget a problem
input_schema: ProblemIR
output_schema: RoutePlan
visible_memory: raw_problem
forbidden_context: candidate_solution_text
allowed_tools: none
failure_policy: rule_engine_fallback
stop_condition: valid_route
max_context_chars: 8000
version: 1
---
Select one primary domain, at most one auxiliary domain, risk, skills, tools, and candidate budget.
