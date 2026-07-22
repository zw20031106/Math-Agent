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
version: 1
---
Extract concise lemmas with conditions and dependencies; all new lemmas remain provisional.
