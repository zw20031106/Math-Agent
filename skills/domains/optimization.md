---
name: optimization
subject: optimization
kind: domain
version: 2.0
triggers: optimization, maximum, minimum, convex, duality, 最优化, 最大值, 最小值
roles: PrimarySolver, AlternativeSolver, VerifierSkeptic, RepairAgent
---
## Triggers

Continuous extrema, convex programs, constrained stationarity, inequalities,
and duality outside specialized operations-research routing.

## Roles

Solvers use stationarity, convexity, or duality; Verifier checks feasibility
and global certificates; Repair fixes local optimality Claims.

## Method decision tree

Define the feasible set, inspect boundaries, solve stationarity/KKT equations
under qualifications, and use convexity or a matching dual value for globality.

## Theorem preconditions

Check compactness/existence, differentiability, convexity, constraint
qualification, feasible signs, and boundary activity.

## Common errors

Do not equate stationarity with global optimality, omit endpoints, accept an
infeasible multiplier, or reverse max/min dual inequalities.

## Counterexample checklist

Test boundaries, nonunique optimizers, inactive constraints, nonconvex
stationary points, and unbounded feasible directions.

## Compatible check types

Use `reasoning`, `necessity`, `sufficiency`, `boundary`,
`theorem_preconditions`, and `symbolic_equivalence`.

## Answer normalization

Return the optimizer and objective separately, with exact coordinates and any
nonuniqueness.

## Trace step guidance

Expose feasible set, candidate conditions, boundary/duality certificate, and
exact optimum.
