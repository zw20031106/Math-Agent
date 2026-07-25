---
name: topology
subject: topology
kind: domain
version: 2.0
triggers: topology, homology, homeomorphism, genus, degree, 拓扑, 同调群, 同胚, 映射度数
roles: PrimarySolver, AlternativeSolver, VerifierSkeptic, RepairAgent
---
## Triggers

Topological spaces, surfaces, homology, induced maps, degree, genus,
homeomorphism, compactness, and connectedness.

## Roles

Solvers use invariants or cellular/algebraic structure; Verifier checks
coefficients/orientation; Repair fixes local invariant Claims.

## Method decision tree

Identify the category and coefficients, choose a standard decomposition or
cell complex, compute invariant groups/maps, and use determinant/degree only
under orientation conventions.

## Theorem preconditions

State coefficients, reduced/unreduced convention, connectedness, basepoints,
orientability, closedness, and induced-map basis.

## Common errors

Do not drop torsion, use orientable formulas for nonorientable surfaces,
confuse Euler characteristic with genus, or take an absolute determinant when
signed degree is requested.

## Counterexample checklist

Check sphere/torus/projective cases, disconnected components, orientation
reversal, torsion, and identity/constant maps.

## Compatible check types

Use `reasoning`, `definition`, `theorem_preconditions`, `necessity`,
`sufficiency`, and `boundary`.

## Answer normalization

Return groups with direct-sum/torsion notation and degrees as signed integers.

## Trace step guidance

Expose decomposition, coefficients/orientation, invariant computation, sanity
checks, and exact result.
