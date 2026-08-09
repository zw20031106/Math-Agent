---
name: gaussian-elimination
version: 3.0
domain: linear_algebra
subdomain: linear system
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: gaussian, row reduction, linear equations
problem_patterns: solve linear system, row echelon
method_family: gaussian-elimination
alternative_skills: rank-nullity
requires: matrix_shape_check
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: matrix_shape_check
---
## Recognition
Use when the problem exposes solve linear system, row echelon.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
Elementary row operations preserve the solution set of a linear system.

## Exact Preconditions
The augmented matrix faithfully represents the equations.

## Procedure
Pivot column by column and record free variables.

## Branch Conditions
Branch by zero pivots and parameter-dependent ranks.

## Failure Modes
Dividing by a symbolic pivot without a nonzero branch loses cases.

## Counterexample Patterns
Test parameter values that make pivots vanish.

## Verification Recipe
Substitute the parametrized solution into the original equations.

## Mini Example
Reduce [[1,1|2],[1,-1|0]] to x=y=1.

## Alternative Strategy
Use matrix inversion when nonsingularity is proven.

## Stop / Escalate Conditions
Escalate to case splits for symbolic pivots.
