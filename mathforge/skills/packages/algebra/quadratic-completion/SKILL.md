---
name: quadratic-completion
version: 3.0
domain: algebra
subdomain: quadratic
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: complete the square, vertex form
problem_patterns: quadratic expression, minimum of quadratic
method_family: quadratic-completion
alternative_skills: polynomial-factorization
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Recognition
Use when the problem exposes quadratic expression, minimum of quadratic.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
Rewrite the quadratic into vertex form while preserving the leading coefficient.

## Exact Preconditions
Leading coefficient is nonzero and the domain is tracked.

## Procedure
Factor the leading coefficient then add and subtract the required square term.

## Branch Conditions
Split by the sign of the leading coefficient and by real or complex domain.

## Failure Modes
Sign loss or an omitted constant changes the extremum.

## Counterexample Patterns
Check a negative leading coefficient and a non-real discriminant.

## Verification Recipe
Expand the completed square and compare every coefficient.

## Mini Example
x^2+6x+5=(x+3)^2-4.

## Alternative Strategy
Use the quadratic formula or derivatives.

## Stop / Escalate Conditions
Escalate when coefficients are symbolic with unresolved sign conditions.
