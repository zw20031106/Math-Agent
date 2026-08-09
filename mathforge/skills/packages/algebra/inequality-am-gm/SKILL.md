---
name: inequality-am-gm
version: 3.0
domain: algebra
subdomain: inequality
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: am-gm, geometric mean
problem_patterns: positive variables, product constraint
method_family: inequality-am-gm
alternative_skills: cauchy-schwarz
requires: numerical_residual
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: numerical_residual
---
## Recognition
Use when the problem exposes positive variables, product constraint.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
For nonnegative terms the arithmetic mean is at least the geometric mean.

## Exact Preconditions
All terms are nonnegative and equality compatibility is checked.

## Procedure
Choose terms whose product matches the target then apply AM-GM.

## Branch Conditions
Branch if signs are unknown or weights differ.

## Failure Modes
Applying AM-GM to negative terms is invalid.

## Counterexample Patterns
Test a negative input and equality at equal terms.

## Verification Recipe
Verify positivity and the equality case.

## Mini Example
For a,b>0, a+b>=2sqrt(ab).

## Alternative Strategy
Use Cauchy-Schwarz or convexity.

## Stop / Escalate Conditions
Escalate when positivity cannot be derived.
