---
name: determinant-expansion
version: 3.0
domain: linear_algebra
subdomain: linear map
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: determinant, cofactor, volume
problem_patterns: compute determinant, singularity
method_family: determinant-expansion
alternative_skills: gaussian-elimination
requires: matrix_shape_check
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: matrix_shape_check
---
## Recognition
Use when the problem exposes compute determinant, singularity.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
The determinant is multilinear alternating and changes predictably under row operations.

## Exact Preconditions
The matrix is square.

## Procedure
Use elimination with tracked swaps and scalings or a structured expansion.

## Branch Conditions
Branch on symbolic zero pivots.

## Failure Modes
Untracked row scaling changes the determinant.

## Counterexample Patterns
Check triangular and singular special cases.

## Verification Recipe
Compare two independent expansions for small matrices.

## Mini Example
det([[a,b],[c,d]])=ad-bc.

## Alternative Strategy
Use eigenvalue products when justified.

## Stop / Escalate Conditions
Escalate for symbolic cases needing pivot splits.
