---
name: argument-principle
version: 3.0
domain: complex_analysis
subdomain: proof
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: argument principle, winding number, zero pole count
problem_patterns: count zeros minus poles, change argument
method_family: argument-principle
alternative_skills: rouche-zero-count
requires: numerical_residual
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: numerical_residual
---
## Recognition
Use when the problem exposes count zeros minus poles, change argument.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
The contour integral of f'/f gives zeros minus poles inside with multiplicity.

## Exact Preconditions
The function is meromorphic and has no zeros or poles on the contour.

## Procedure
Check boundary exclusions then evaluate winding or integral.

## Branch Conditions
Branch when poles are present or orientation reverses.

## Failure Modes
Boundary zeros make the count unstable.

## Counterexample Patterns
Test a nearby parameter where a zero crosses the contour.

## Verification Recipe
Compare with known factorization for a simple case.

## Mini Example
For f=z^n on the unit circle the argument changes by 2pi n.

## Alternative Strategy
Use Rouche theorem.

## Stop / Escalate Conditions
Escalate when boundary nonvanishing is unproved.
