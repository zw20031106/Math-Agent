---
name: strategy-progress-assessment
version: 3.0
domain: general
subdomain: reasoning_control
kind: method
roles: PrimarySolver,AlternativeSolver,LemmaCurator,VerifierSkeptic,RepairAgent
triggers: stalled proof, repeated attempt, progress assessment, strategy switch, long horizon
problem_patterns: unresolved obligations, repeated equivalent candidates, high uncertainty
method_family: metacognitive-progress-control
alternative_skills: proof-strategy-selection,proof-obligation
description: Inspect public reasoning state and choose the next useful action without treating repetition as progress.
negative_triggers: first-turn complete candidate, no unresolved obligation, private chain-of-thought request
required_observables: open obligations, last public artifact, unresolved conflict, remaining model time
requires: answer_type_check
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: answer_type_check
---
## Recognition
Use after a public turn when the host needs a deterministic, auditable recommendation to continue, decompose, request a lemma, switch method, or abstain.

## Do Not Use When
Do not call this a correctness verifier. Do not restart a complete candidate merely because its wording differs, and do not infer progress from hidden thoughts, token count, or a repeated answer.

## Core Theorem
Progress is an observable state transition: a new claim, step, evidence record, closed obligation, resolved conflict, or explicitly justified strategy change. A recommendation is a control signal, not a proof of the underlying mathematics.

## Exact Preconditions
Provide the current candidate/version, public trace tail, open and closed obligations, findings, consumed artifact versions, remaining model-call window, and the last action. If these are absent, the only safe recommendation is `abstain` or `request lemma` with a missing-state finding.

## Procedure
1. Inventory what changed since the previous turn; deduplicate semantically equivalent artifacts.
2. Rank open obligations by blocking impact, evidence gap, and expected information value.
3. Check whether the current method has a concrete next step; otherwise propose one alternative skill.
4. Choose exactly one recommendation: `continue`, `decompose`, `request lemma`, `switch alternative`, or `abstain`.
5. State the observable artifact that must be produced next and the stop condition.

## Branch Conditions
Continue only when a new bounded step is available. Decompose when one obligation contains independent subclaims. Request a lemma when a named dependency blocks closure. Switch when the current method has a recorded failure signal. Abstain when no safe progress is possible or the remaining model window cannot support closure.

## Failure Modes
Counting a longer response as progress, issuing an unconditional progress-then-synthesis duplicate, ignoring a stale plan/version, or selecting a tool that cannot close the obligation. A recommendation that has no expected observable is invalid.

## Counterexample Patterns
Use a loop that repeats the same algebra, two candidates with identical claims, a proof with one unclosed side condition, and a nearly expired model window. Each must produce a different control decision rather than a fabricated success.

## Verification Recipe
Mathematical verification remains with the claim-specific verifier. Host verification uses `answer_type_check` only to check that the recommendation has the allowed action and observable fields; it does not prove correctness. This hook is answer-shape support, not mathematical proof.

## Mini Example
If a continuity proof has established the bound but not chosen an epsilon-dependent delta, recommend `continue` with the delta obligation. If the same bound was emitted twice, recommend `switch alternative` or `abstain`, not another duplicate turn.

## Alternative Strategy
Use a fixed obligation queue for short proofs, or a claim-local repair plan when one finding is already isolated. Keep the recommendation service deterministic when no model turn is needed.

## Stop / Escalate Conditions
Escalate when state versions disagree, a required artifact was not consumed, the next action would repeat a prior artifact, or the remaining window lacks finalization reserve. Never close an obligation from the progress recommendation alone.
