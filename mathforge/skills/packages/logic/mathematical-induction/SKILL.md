---
name: mathematical-induction
version: 3.0
domain: logic
subdomain: proof
kind: method
roles: PrimarySolver,AlternativeSolver,LemmaCurator,VerifierSkeptic,RepairAgent
triggers: induction, for all n, recurrence proof, base case, inductive step
problem_patterns: indexed integer statement, recursively defined object, well-founded measure
method_family: induction
alternative_skills: proof-strategy-selection,case-split-wlog
description: Prove an indexed family by a valid base and an explicitly quantified step over a well-founded index.
negative_triggers: continuous parameter without discretization, missing base, circular step, finite samples only
required_observables: index domain, base set, induction hypothesis, target step, well-founded measure
requires: small_case_enumeration
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: small_case_enumeration
---
## Recognition
Use for statements indexed by natural numbers, finite structures with a size measure, or recursively generated objects where smaller instances support the next case.

## Do Not Use When
Do not infer an infinite theorem from a few enumerated cases, do not use induction on a non-well-founded relation, and do not let the induction hypothesis assume the target at the same index.

## Core Theorem
If P holds for every base index and P(k) implies P(k+1) for every k in the stated domain, then P holds for all indices reachable from the base. Strong or structural induction changes the hypothesis set but not the need for a well-founded measure.

## Exact Preconditions
State the index set and its order, all base cases, and the exact induction hypothesis. For strong/structural induction specify which smaller indices or substructures are available and why the measure decreases. Check side conditions at the smallest index.

## Procedure
1. Write P(n) with domains and parameters fixed.
2. Prove every base case separately; do not hide multiple bases in “obvious.”
3. Assume only the permitted induction hypothesis and derive P(k+1) (or the next structure).
4. Check that recursive calls decrease the well-founded measure and that all branches are covered.
5. Reconcile the base and step versions with the original quantifiers before closing the obligation.

## Branch Conditions
Use ordinary induction for successor indices, strong induction when several smaller cases are needed, and structural induction when constructors define the object. Finite induction ranges still require an endpoint convention.

## Failure Modes
An omitted base, an invalid starting index, a step that only handles even k, a circular use of P(k+1), or a recursive decomposition that does not decrease. A correct step cannot repair a false base.

## Counterexample Patterns
Check n=0 and the first index after every claimed threshold; test a recurrence with exceptional initial data and a measure that can stay equal. A statement true for the first six cases may fail at the seventh.

## Verification Recipe
Host verification uses `small_case_enumeration` for supplied finite base/edge cases only. It is exact for those cases but cannot prove the induction step or the universal theorem; label it supporting evidence and require a written quantified step.

## Mini Example
For 1+2+...+n=n(n+1)/2, verify n=1, assume the formula at k, add k+1, and simplify the resulting expression under the integer-domain assumption.

## Alternative Strategy
Use a direct invariant, a recurrence unrolling, or a minimal-counterexample argument when the induction step is opaque. Preserve the same well-founded obligation.

## Stop / Escalate Conditions
Escalate when the base set is unclear, the measure is not well-founded, the step has an uncovered constructor/case, or finite enumeration is the only evidence.
