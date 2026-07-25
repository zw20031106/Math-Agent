---
name: geometry
subject: geometry
kind: domain
version: 2.0
triggers: triangle, circle, angle, Euclidean geometry, 三角形, 圆, 角
roles: PrimarySolver, AlternativeSolver, VerifierSkeptic, RepairAgent
---
## Triggers

Euclidean triangles, circles, angles, lengths, incidence, coordinates, and
vector geometry.

## Roles

Solvers choose synthetic, coordinate, or vector methods; Verifier checks
incidence and degeneracy; Repair fixes local geometric Claims.

## Method decision tree

Prefer a short synthetic theorem when its configuration is explicit; otherwise
choose coordinates or vectors that preserve symmetry and constraints.

## Theorem preconditions

Check collinearity/noncollinearity, point order, directed-angle convention,
nonzero lengths, circle membership, and similarity/congruence hypotheses.

## Common errors

Do not infer a diagram fact, divide by a zero length, lose orientation, or
accept an extraneous coordinate branch.

## Counterexample checklist

Test degenerate triangles, tangent/coincident cases, reflected configurations,
and boundary angles.

## Compatible check types

Use `reasoning`, `definition`, `symbolic_equivalence`, `boundary`, and
`theorem_preconditions`.

## Answer normalization

Return exact lengths/angles/ratios and state units or orientation.

## Trace step guidance

Expose configuration facts, theorem or coordinate choice, algebraic check,
degeneracy handling, and result.
