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
description: Use the real symmetric or complex Hermitian spectral theorem only after the inner-product hypotheses are verified.
negative_triggers: merely diagonalizable, nonsymmetric matrix, unspecified inner product
required_observables: finite dimensional inner product, symmetry or self-adjointness, orthonormal basis
requires: matrix_shape_check
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: matrix_shape_check
---
## Recognition
Use when the target concerns orthogonal/unitary diagonalization, an orthonormal eigenbasis, or spectral decomposition of a finite-dimensional self-adjoint operator.

## Do Not Use When
Do not apply merely because eigenvalues exist. A diagonalizable nonsymmetric matrix need not be orthogonally diagonalizable, and “symmetric” depends on the specified inner product and field.

## Core Theorem
Every real symmetric matrix is orthogonally diagonalizable, and every complex Hermitian matrix is unitarily diagonalizable with real eigenvalues. The statement is finite-dimensional and inner-product dependent.

## Exact Preconditions
State the scalar field, finite dimension, and inner product. Verify A=A^T over the reals or A=A* over the complexes in that inner product; then verify the eigenvectors can be normalized to an orthonormal basis.

## Procedure
1. Check the adjoint/symmetry identity with the correct conjugation.
2. Find eigenvalues and eigenspaces, retaining algebraic/geometric multiplicities.
3. Orthogonalize within repeated eigenspaces and normalize.
4. Form Q and verify Q*Q=I and Q*AQ is diagonal, including dimensions.
5. State the resulting spectral sum and its field of scalars.

## Branch Conditions
Separate real symmetric and complex Hermitian cases, and treat a nonstandard inner product by computing the corresponding adjoint rather than using A^T blindly.

## Failure Modes
Confusing ordinary transpose with conjugate transpose, checking only eigenvalue reality, or assuming any diagonalization is orthogonal leaves the theorem unproved.

## Counterexample Patterns
Use a nonsymmetric matrix with distinct eigenvalues to show diagonalizable does not imply orthogonally diagonalizable. Change the inner product and recheck the adjoint relation.

## Verification Recipe
`matrix_shape_check` verifies only dimensions and rectangular shape; it cannot verify symmetry, unitarity, or diagonalization. The Verifier must check A=A* and Q*Q=I/Q*AQ diagonal explicitly; a shape pass is only a structural support record.

## Mini Example
A real diagonal matrix is symmetric, its standard basis is orthonormal, and Q=I gives the spectral decomposition directly.

## Alternative Strategy
Use general eigenvalue diagonalization when orthogonality is not available, or use quadratic-form arguments when the target is an extremal property.

## Stop / Escalate Conditions
Escalate when the inner product, adjoint relation, field, or orthonormal basis is unspecified. Do not report a spectral theorem pass from matrix shape alone.

