---
name: linear-algebra
subject: linear-algebra
kind: domain
version: 2.0
triggers: matrix, vector, eigenvalue, linear map
roles: PrimarySolver, AlternativeSolver, VerifierSkeptic, RepairAgent
---
## Triggers

General matrix/vector calculations, eigenvalues, row spaces, linear maps, rank,
and nullity.

## Roles

Solvers use row-space, spectral, or invariant-map methods; Verifier checks
shape; Repair fixes local matrix Claims.

## Method decision tree

Check dimensions first, then use row reduction for systems/rank, spectral
methods for square operators, and basis-free invariants where possible.

## Theorem preconditions

State field, matrix dimensions, basis, squareness, invertibility, and
diagonalizability assumptions.

## Common errors

Do not multiply incompatible shapes, confuse row/column conventions, or infer
diagonalizability from distinct-looking formulas.

## Counterexample checklist

Test singular/zero matrices, repeated eigenvalues, rectangular shapes, and
basis changes.

## Compatible check types

Use `matrix_shape_check`, `symbolic_equivalence`, `reasoning`, and
`answer_type_check`.

## Answer normalization

Return vectors in stated order, matrices with explicit rows, and exact scalar
invariants.

## Trace step guidance

Expose shapes, chosen invariant/operation, calculation, validation, and exact
output.
