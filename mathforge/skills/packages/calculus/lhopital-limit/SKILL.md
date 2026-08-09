---
name: lhopital-limit
version: 3.0
domain: calculus
subdomain: limit
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: lhopital, 0/0, infinity/infinity
problem_patterns: indeterminate quotient limit, derivative ratio
method_family: lhopital-limit
alternative_skills: taylor-remainder
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Recognition
Use when the problem exposes indeterminate quotient limit, derivative ratio.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
L'Hopital applies to specified indeterminate quotient forms under neighborhood hypotheses.

## Exact Preconditions
Numerator and denominator are differentiable nearby and denominator derivative is nonzero as required.

## Procedure
Confirm the form then differentiate numerator and denominator once per justified step.

## Branch Conditions
Reassess the indeterminate form after every application.

## Failure Modes
Applying the rule to non-indeterminate forms changes the problem.

## Counterexample Patterns
Test a form such as 0 times infinity before rewriting.

## Verification Recipe
Compare with algebraic simplification or series expansion.

## Mini Example
lim sin x/x=lim cos x=1 as x->0.

## Alternative Strategy
Use squeeze theorem or Taylor expansion.

## Stop / Escalate Conditions
Escalate if the derivative ratio has no controlled limit.
