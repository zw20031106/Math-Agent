---
name: partial-differential-equations
subject: partial-differential-equations
kind: domain
version: 2.0
triggers: PDE, heat equation, wave equation, Laplacian, boundary value, 偏微分方程, 热方程, 波动方程
roles: PrimarySolver, AlternativeSolver, VerifierSkeptic, RepairAgent
---
## Triggers

Heat, wave, Laplace/Poisson equations, eigenfunction expansions, radial
solutions, initial-boundary value problems.

## Roles

Solvers choose separation, spectral expansion, or radial reduction; Verifier
checks PDE, data, and regularity; Repair patches failed modes or boundaries.

## Method decision tree

Exploit symmetry first, otherwise use the spatial eigenbasis, solve each modal
ODE including resonance/forcing, and impose initial and boundary data.

## Theorem preconditions

Check domain geometry, boundary type, compatibility at corners, regularity,
eigenfunction normalization, and convergence needed for differentiation.

## Common errors

Do not omit a forced resonant term, use the wrong wave frequency, forget radial
regularity at the origin, or satisfy only the PDE but not the data.

## Counterexample checklist

Verify boundary and initial values directly, inspect zero modes, the origin,
sign conventions for the Laplacian, and energy dimensions.

## Compatible check types

Use `symbolic_equivalence`, `reasoning`, `boundary`, `interchange`, and
`theorem_preconditions`.

## Answer normalization

State the solution/value with domain and time, preserving exact exponentials,
trigonometric factors, and series when required.

## Trace step guidance

Expose basis or symmetry choice, modal equation, data enforcement, direct
check, and requested evaluation.
