---
role: LemmaCurator
objective: extract reusable problem-local lemmas
input_schema: exploration_claims
output_schema: LemmaCard[]
visible_memory: claims+obligations+evidence
forbidden_context: rejected_lemmas_as_facts
allowed_tools: none
failure_policy: return_empty_lemma_list
stop_condition: structured_lemmas
max_context_chars: 16000
version: 2
execution_mode: inactive_review_template
---
Inactive review template. Production lemma curation is a deterministic host
service under ADR-001 and does not render this contract into model messages.
