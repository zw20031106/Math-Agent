---
name: differential-equations
subject: differential-equations
kind: domain
version: 2.0
triggers: differential equation, ODE, PDE, initial value, boundary value
roles: PrimarySolver, AlternativeSolver, VerifierSkeptic, RepairAgent
---
## Triggers

Generic differential-equation wording before ODE/PDE-specific routing is
available.

## Roles

Solvers classify and reduce; Verifier checks data; Repair corrects failed local
equation Claims.

## Method decision tree

Classify ordinary versus partial, order, linearity, coefficients, and data,
then delegate to separation, spectral, or constructive computation.

## Theorem preconditions

Check coefficient regularity, domain, initial/boundary compatibility,
uniqueness assumptions, and singular points.

## Common errors

Do not solve the homogeneous equation only, omit constants/modes, or satisfy
the equation while violating data.

## Counterexample checklist

Substitute back, check every datum, inspect equilibrium/zero modes and singular
boundaries.

## Compatible check types

Use `symbolic_equivalence`, `reasoning`, `boundary`, `existence`, and
`uniqueness`.

## Answer normalization

State variables, domain/interval, and exact constants or requested evaluation.

## Trace step guidance

Expose classification, reduction, data enforcement, direct verification, and
final result.
