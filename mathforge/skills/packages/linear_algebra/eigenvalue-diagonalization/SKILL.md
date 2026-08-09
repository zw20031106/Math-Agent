---
name: eigenvalue-diagonalization
version: 3.0
domain: linear_algebra
subdomain: linear map
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: eigenvalue, diagonalizable, eigenvector
problem_patterns: diagonalize matrix, spectrum
method_family: eigenvalue-diagonalization
alternative_skills: jordan-form
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Recognition
Use when the problem exposes diagonalize matrix, spectrum.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
A matrix is diagonalizable exactly when it has a basis of eigenvectors.

## Exact Preconditions
The scalar field is specified and algebraic/geometric multiplicities are tracked.

## Procedure
Find characteristic roots then bases for each eigenspace.

## Branch Conditions
Branch by repeated eigenvalues and field extensions.

## Failure Modes
Distinct eigenvalues suffice but are not necessary.

## Counterexample Patterns
Test a Jordan block with one eigenvector.

## Verification Recipe
Check AP=PD and that P is invertible.

## Mini Example
diag(2,3) is already diagonal with standard eigenvectors.

## Alternative Strategy
Use Jordan form or the spectral theorem.

## Stop / Escalate Conditions
Escalate when exact roots are unavailable or the field is ambiguous.
