---
name: vieta-relations
version: 3.0
domain: algebra
subdomain: polynomial
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: vieta, sum of roots, product of roots
problem_patterns: root sums, coefficient relations
method_family: vieta-relations
alternative_skills: symmetric-polynomial
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Recognition
Use when the problem exposes root sums, coefficient relations.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
Elementary symmetric functions of roots equal signed coefficient ratios.

## Exact Preconditions
The polynomial degree and nonzero leading coefficient are known.

## Procedure
Normalize by the leading coefficient and map each coefficient to its symmetric sum.

## Branch Conditions
Branch for missing roots or multiplicities.

## Failure Modes
Using only real roots can omit complex roots counted by the theorem.

## Counterexample Patterns
Check a quadratic with a repeated root.

## Verification Recipe
Reconstruct coefficients from the claimed symmetric sums.

## Mini Example
For x^2-5x+6 roots sum to 5 and multiply to 6.

## Alternative Strategy
Solve or factor the polynomial directly.

## Stop / Escalate Conditions
Escalate if only a subset of roots is constrained.
