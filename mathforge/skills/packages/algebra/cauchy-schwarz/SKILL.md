---
name: cauchy-schwarz
version: 3.0
domain: algebra
subdomain: inequality
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: cauchy, schwarz, sum of squares
problem_patterns: inner product bound, sum ratio
method_family: cauchy-schwarz
alternative_skills: inequality-am-gm
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Recognition
Use when the problem exposes inner product bound, sum ratio.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
The squared inner product is bounded by the product of squared norms.

## Exact Preconditions
Vectors lie in a real or complex inner-product space.

## Procedure
Choose vector components then apply the inequality and identify equality proportionality.

## Branch Conditions
Branch between Engel form and standard inner product form.

## Failure Modes
A missing positivity condition can invalidate division in Engel form.

## Counterexample Patterns
Test zero denominators and proportional vectors.

## Verification Recipe
Expand both norms and check equality conditions.

## Mini Example
(a+b)^2<=2(a^2+b^2).

## Alternative Strategy
Use AM-GM or Jensen.

## Stop / Escalate Conditions
Escalate when the proposed denominator can vanish.
