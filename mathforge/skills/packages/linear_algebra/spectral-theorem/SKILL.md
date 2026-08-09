---
name: spectral-theorem
version: 3.0
domain: linear_algebra
subdomain: linear map
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: spectral theorem, symmetric matrix, self-adjoint
problem_patterns: orthogonal diagonalization, Hermitian
method_family: spectral-theorem
alternative_skills: eigenvalue-diagonalization
requires: matrix_shape_check
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: matrix_shape_check
---
## Recognition
Use when the problem exposes orthogonal diagonalization, Hermitian.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
Real symmetric or complex Hermitian operators admit an orthonormal eigenbasis.

## Exact Preconditions
Symmetry or self-adjointness is verified in the correct inner product.

## Procedure
Find eigenvalues and orthonormalize within eigenspaces.

## Branch Conditions
Branch between real symmetric and complex Hermitian cases.

## Failure Modes
A merely diagonalizable matrix need not be orthogonally diagonalizable.

## Counterexample Patterns
Test a nonsymmetric diagonalizable matrix.

## Verification Recipe
Check Q*Q=I and Q*AQ is diagonal.

## Mini Example
A real diagonal matrix satisfies the theorem directly.

## Alternative Strategy
Use general eigenvalue diagonalization.

## Stop / Escalate Conditions
Escalate if the inner product is nonstandard and unspecified.
