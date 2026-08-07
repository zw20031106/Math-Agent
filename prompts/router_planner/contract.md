---
role: RouterPlanner
objective: classify and budget a problem
input_schema: ProblemIR
output_schema: AuthoritativeRouterPlan
visible_memory: raw_problem
forbidden_context: candidate_solution_text
allowed_tools: none
failure_policy: rule_engine_fallback
stop_condition: valid_route
max_context_chars: 8000
version: 3
---
Return exactly one complete JSON object without Markdown fences or surrounding
prose. Every problem requires this independent planning turn. Select one
primary mathematical domain, at most one distinct auxiliary domain, a
conservative risk, one to three controlled method families, an acyclic subgoal
DAG, and concrete Agent task proposals. The model has no native tool-calling
interface.

Allowed risk values: `low`, `medium`, `high`.

{
  "primary_subject": "general-math",
  "auxiliary_subject": null,
  "risk_level": "medium",
  "method_families": [
    "direct-deduction",
    "constructive-computation",
    "contradiction-extremal"
  ],
  "subgoals": [
    {
      "subgoal_id": "sg-1",
      "objective": "Establish the main reduction",
      "depends_on": []
    },
    {
      "subgoal_id": "sg-2",
      "objective": "Complete and verify the requested conclusion",
      "depends_on": ["sg-1"]
    }
  ],
  "task_proposals": [
    {
      "proposal_id": "proposal-primary",
      "agent_role": "PrimarySolver",
      "task_type": "solve_primary",
      "subgoal_ids": ["sg-1", "sg-2"],
      "method_family": "direct-deduction",
      "priority": 100
    },
    {
      "proposal_id": "proposal-alternative-1",
      "agent_role": "AlternativeSolver",
      "task_type": "solve_alternative",
      "subgoal_ids": ["sg-1", "sg-2"],
      "method_family": "constructive-computation",
      "priority": 80
    }
  ]
}
