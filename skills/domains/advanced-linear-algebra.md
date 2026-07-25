---
name: advanced-linear-algebra
subject: advanced-linear-algebra
kind: domain
version: 2.0
triggers: Jordan, minimal polynomial, centralizer, Kronecker, quadratic form, 矩阵, 惯性指数
roles: PrimarySolver, AlternativeSolver, VerifierSkeptic, RepairAgent
---
## Triggers

Jordan structure, minimal and characteristic polynomials, tensor/Kronecker
operations, centralizers, rank/nullity, spectra, and quadratic forms.

## Roles

Solvers use row-space, spectral, or invariant-map methods; Verifier checks
dimensions and polynomial identities; Repair corrects failed local claims.

## Method decision tree

Use kernel growth for nilpotent Jordan blocks, determinant identities for low
rank products, spectral mapping for matrix functions, and congruence for
quadratic forms.

## Theorem preconditions

Check base field, dimensions, square-matrix requirements, diagonalizability,
rank compatibility, and whether similarity or congruence is intended.

## Common errors

Do not transpose dimensions incorrectly, confuse algebraic/geometric
multiplicity, or infer Jordan form from the characteristic polynomial alone.

## Counterexample checklist

Test singular and zero blocks, repeated eigenvalues, defective matrices,
rectangular shapes, and real versus complex canonical forms.

## Compatible check types

Use `matrix_shape_check`, `symbolic_equivalence`, `reasoning`,
`theorem_preconditions`, and `answer_type_check`.

## Answer normalization

Order Jordan block sizes consistently; state polynomial variable conventions,
matrix dimensions, and inertia as an ordered triple.

## Trace step guidance

Expose dimension data, invariant calculation, canonical-form conclusion, and
the exact requested scalar/vector/polynomial.
