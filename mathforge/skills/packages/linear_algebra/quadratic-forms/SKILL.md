---
name: quadratic-forms
version: 3.0
domain: linear_algebra
subdomain: optimization
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: quadratic form, positive definite, hessian
problem_patterns: classify quadratic form, definiteness
method_family: quadratic-forms
alternative_skills: spectral-theorem
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Recognition
Use when the problem exposes classify quadratic form, definiteness.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
For symmetric matrices definiteness is characterized by eigenvalues or Sylvester criteria.

## Exact Preconditions
Replace a matrix by its symmetric part and state the scalar field.

## Procedure
Compute principal minors or eigenvalue signs then classify.

## Branch Conditions
Branch when minors vanish or parameters cross sign boundaries.

## Failure Modes
Positive diagonal entries alone do not imply positive definiteness.

## Counterexample Patterns
Test directions aligned with negative eigenvectors.

## Verification Recipe
Evaluate the form on a diagonalizing basis.

## Mini Example
x^2+2y^2 is positive definite.

## Alternative Strategy
Use completing squares or the spectral theorem.

## Stop / Escalate Conditions
Escalate for semidefinite parameter boundaries.
