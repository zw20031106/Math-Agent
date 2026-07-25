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
version: 2
---
Return exactly one complete JSON object without Markdown fences or surrounding
prose. Select one primary mathematical domain, at most one distinct auxiliary
domain, a conservative risk, and three controlled method families. The model
has no native tool-calling interface.

Allowed risk values: `low`, `medium`, `high`.

{
  "primary_subject": "general-math",
  "auxiliary_subject": null,
  "risk_level": "medium",
  "method_families": [
    "direct-deduction",
    "constructive-computation",
    "contradiction-extremal"
  ]
}
