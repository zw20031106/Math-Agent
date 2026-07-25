---
name: differential-geometry
subject: differential-geometry
kind: domain
version: 2.0
triggers: surface, Gaussian curvature, geodesic curvature, first fundamental form, 曲面, 高斯曲率, 测地曲率
roles: PrimarySolver, AlternativeSolver, VerifierSkeptic, RepairAgent
---
## Triggers

Parametric surfaces, first/second fundamental forms, Gaussian curvature,
normal curvature, geodesic curvature, spheres and tori.

## Roles

Solvers use local coordinates or invariant formulas; Verifier checks
orientation-independent claims and regularity; Repair fixes failed derivatives
or normalizations.

## Method decision tree

Differentiate the parametrization, compute metric coefficients and a unit
normal, then use fundamental-form curvature formulas; exploit known sphere or
surface-of-revolution formulas only after matching conventions.

## Theorem preconditions

Check regularity, nonzero cross product, radius/parameter ranges, orientation,
unit-speed requirements, and whether an absolute curvature is requested.

## Common errors

Do not use an unnormalized normal, swap principal-curvature signs, confuse
Gaussian/geodesic curvature, or omit the ambient radius factor.

## Counterexample checklist

Check flat limits, inner versus outer torus equators, poles, orientation
reversal, and dimensional units of curvature.

## Compatible check types

Use `reasoning`, `definition`, `symbolic_equivalence`,
`theorem_preconditions`, and `boundary`.

## Answer normalization

State curvature sign convention or return the requested absolute value with
exact units \(1/R\) or \(1/R^2\).

## Trace step guidance

Expose derivatives/metric, normal convention, curvature formula, substitution,
and exact result.
