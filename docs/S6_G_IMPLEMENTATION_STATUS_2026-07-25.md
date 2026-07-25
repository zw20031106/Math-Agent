# S6-G Implementation Status — 2026-07-25

## Result

E6 is implemented. The advanced execution loop is now driven by Host-owned
Evidence and exposes enough public Trace data to reconstruct why every
candidate was accepted, repaired, superseded, or rejected.

## Implemented invariants

- `selected_tools` gates Claim-level execution. A route omission or an
  argument that cannot be reconstructed from the controlled Claim syntax
  becomes explicit `unknown` Evidence.
- Syntax and answer-shape capabilities never promote mathematical truth.
- The initial allocation does not speculate about Repair or Lemma work.
  After initial Evidence, the allocation is rebuilt without exceeding six
  model calls or reducing any already-used/required stage.
- Hard Evidence failures receive a Repair reserve when reachable; otherwise
  `call_allocation_rebalanced` records the budget reason.
- Repair remains Claim-local and versioned. Its dependency impact closure is
  reverified, lower-quality Evidence rolls back the proposal, and Trace
  contains structured before/after Claim fields.
- Lemma execution requires a high-risk proof or derivation, a dependency chain
  of at least three Claims, and a semantically verified local Claim. Trace
  contains full Lemma cards, round state, conditions, verification status,
  downstream candidate use, and full expanded-candidate re-verification.
- `candidate_final_states` records Claim states, Evidence failures, proof
  obligations, and final reason codes for every generated candidate.
- Timed-out model threads are audited as background tails. Their late return
  cannot overwrite the already-returned answer, Trace, or RunMetrics snapshot.

## Verification mapping

| Acceptance item | Verification |
|---|---|
| Applicable Claim tool checks execute | Claim verification and runtime tests |
| Syntax does not prove truth | Nonsemantic hard-pass regression |
| Repair budget or unreachable reason | Runtime reallocation and proof-pressure tests |
| Repair closure and rollback | Repair service/runtime regressions |
| Lemma truly triggers | History-free Lemma E2E with dependency chain |
| Expanded candidate fully reverified | Per-stage verification-chain Trace assertion |
| Candidate end state explainable | `candidate_final_states` Trace assertion |
| Background tail observable and inert | Slow-client deadline regressions |

## Remaining external gate

Intern-S2 live quality evaluation is intentionally outside this deterministic
phase commit. E7 owns the per-case runner, watchdog, resume, and output
lifecycle used for that evaluation.
