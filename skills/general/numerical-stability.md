---
name: numerical-stability
subject: general-math
kind: general
version: 2.0
triggers: approximation, error, condition number, iteration, 数值, 误差
roles: PrimarySolver, AlternativeSolver, VerifierSkeptic
---
## Triggers

Use for numerical approximation, iterative methods, error estimates,
conditioning, cancellation, and finite-precision comparisons.

## Roles

Solvers expose a stable computation; Verifier distinguishes supporting numeric
evidence from exact proof.

## Method decision tree

Prefer an exact formula, then a stable reformulation, bound truncation and
roundoff separately, and test representative scales.

## Theorem preconditions

State convergence hypotheses, norm, tolerance, stopping rule, matrix
nonsingularity, and any smoothness required by an error theorem.

## Common errors

Do not subtract nearly equal numbers blindly, infer convergence from two
iterations, or report an unsigned error when a signed error is requested.

## Counterexample checklist

Test near-singular inputs, scale changes, boundary step sizes, cancellation,
slow convergence, and alternative initial values.

## Compatible check types

Use `numerical_residual`, `matrix_shape_check`, `reasoning`, or
`symbolic_equivalence`.

## Answer normalization

Return exact rational iteration values when available; otherwise state digits,
tolerance, and whether the value is approximate.

## Trace step guidance

Expose the formula, stability risk, bound or residual, and the final normalized
numeric answer.
