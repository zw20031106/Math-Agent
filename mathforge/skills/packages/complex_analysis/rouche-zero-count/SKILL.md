---
name: rouche-zero-count
version: 3.0
domain: complex_analysis
subdomain: proof
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: rouche, zeros inside contour, dominates
problem_patterns: count complex zeros, contour dominance
method_family: rouche-zero-count
alternative_skills: argument-principle
requires: numerical_residual
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: numerical_residual
---
## Recognition
Use when the problem exposes count complex zeros, contour dominance.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
If |g|<|f| on a simple closed contour then f and f+g have equal zero counts inside.

## Exact Preconditions
Both functions are holomorphic on and inside the contour and strict boundary dominance holds.

## Procedure
Choose a dominant term prove the strict bound on the entire contour then count its zeros.

## Branch Conditions
Branch by contour radius or boundary arcs.

## Failure Modes
A non-strict inequality is insufficient without extra argument.

## Counterexample Patterns
Test equality points on the contour.

## Verification Recipe
Minimize the dominance margin over the full boundary.

## Mini Example
On |z|=2, z^3 dominates z+1 when 8>3.

## Alternative Strategy
Use the argument principle or direct factorization.

## Stop / Escalate Conditions
Escalate when strict dominance cannot be certified globally.
