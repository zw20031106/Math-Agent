---
name: ordinary-differential-equations
subject: ordinary-differential-equations
kind: domain
version: 2.0
triggers: ODE, initial value, y prime, linear system, Euler equation, 常微分方程, 初值问题
roles: PrimarySolver, AlternativeSolver, VerifierSkeptic, RepairAgent
---
## Triggers

First/second-order ODEs, initial-value problems, linear systems, Euler
equations, separable/Bernoulli/Riccati forms, and resonance.

## Roles

Solvers choose transformations or spectral system methods; Verifier checks the
equation and initial data; Repair corrects failed local substitutions.

## Method decision tree

Classify order and linearity; try separation or Bernoulli substitution,
characteristic roots for constant coefficients, logarithmic time for Euler
equations, and matrix exponentials for systems.

## Theorem preconditions

Check the interval, singular points, existence/uniqueness hypotheses, initial
time, coefficient continuity, and invertibility of substitutions.

## Common errors

Do not divide by a solution that may vanish, omit a resonant factor, apply
initial data before forming the general solution, or cross a singular point.

## Counterexample checklist

Substitute the solution back, verify every initial derivative, test equilibrium
solutions, singular endpoints, and domain of logarithms.

## Compatible check types

Use `symbolic_equivalence`, `reasoning`, `existence`, `uniqueness`,
`theorem_preconditions`, and `boundary`.

## Answer normalization

State the solution on its maximal justified interval and evaluate the exact
requested value.

## Trace step guidance

Expose classification, substitution/general solution, initial-condition
resolution, verification, and final value.
