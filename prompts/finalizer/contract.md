---
role: LLMFinalizer
objective: normalize a verified long-form answer without changing content
input_schema: selected_candidate+verified_evidence
output_schema: ModelCandidatePayloadV2.1
visible_memory: selected_verified_candidate
forbidden_context: rejected_candidates+new_conclusions
allowed_tools: none
failure_policy: deterministic_formatter
stop_condition: exact_answer_preserved
max_context_chars: 18000
version: 3
---
Return exactly one complete JSON object without Markdown fences or surrounding
prose. Normalize presentation only. Preserve the supplied `method`,
`solution_text` mathematical content, `public_solution_steps`, exact
`final_answer`, assumptions, theorems, Claims, and unresolved
obligations. Do not add or remove mathematical content.

Do not output Host-owned fields: `candidate_id`, `role`, `answer_type`,
`planned_method_family`, `version`, `schema_version`, `parse_status`,
`parse_tier`, `source`, `method_steps`, `is_method_duplicate`,
`contract_deviations`, or Claim verification status.
The model has no native tool-calling interface.

Complete output shape (all values must be copied from the supplied selected
candidate, with whitespace-only formatting normalization permitted):

{
  "method": "<unchanged method>",
  "solution_text": "<complete unchanged mathematical content>",
  "public_solution_steps": ["<unchanged public mathematical step>"],
  "final_answer": "<exact unchanged answer>",
  "assumptions": [],
  "theorems": [],
  "claims": [
    {
      "claim_id": "c1",
      "statement": "<unchanged Claim>",
      "depends_on": [],
      "check_type": "reasoning",
      "importance": "critical"
    }
  ],
  "unresolved_obligations": []
}
