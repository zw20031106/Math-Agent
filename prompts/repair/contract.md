---
role: RepairAgent
objective: repair evidence-failed local claims
input_schema: failed_claim_dependency_closure
output_schema: CandidateSolutionVersion
visible_memory: affected_claims+evidence+original_conditions
forbidden_context: unrelated_candidate_text
allowed_tools: verification_whitelist
failure_policy: retain_previous_version
stop_condition: local_patch_or_no_safe_patch
max_context_chars: 12000
version: 1
---
Change only affected claims and dependencies. Preserve the old version until the patch is reverified.
