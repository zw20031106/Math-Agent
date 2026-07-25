---
name: numerical-analysis
subject: numerical-analysis
kind: domain
version: 2.0
triggers: Simpson, Newton method, interpolation, Gauss-Seidel, condition number, 数值分析, 误差, 条件数
roles: PrimarySolver, AlternativeSolver, VerifierSkeptic, RepairAgent
---
## Triggers

Quadrature, root iterations, interpolation, stationary linear iterations,
condition numbers, truncation error, and stability.

## Roles

Solvers compute exact iterates/error formulas; Verifier checks convergence and
stability; Repair fixes local numerical Claims.

## Method decision tree

Write the exact numerical formula, compute rationally when feasible, identify
the relevant error theorem or iteration matrix, then analyze convergence and
conditioning.

## Theorem preconditions

State smoothness order, nodes/step, initial iterate, nonsingularity, matrix
splitting, norm, tolerance, and convergence conditions.

## Common errors

Do not confuse \(I-S\) with absolute error, miscount iterations, use the wrong
interpolation multiplicity, or compute only \(\|A\|\) for a condition number.

## Counterexample checklist

Check polynomial exactness, substitute interpolation data, evaluate the
iteration spectral radius, perturb inputs, and verify \(A^{-1}\).

## Compatible check types

Use `numerical_residual`, `matrix_shape_check`, `symbolic_equivalence`,
`reasoning`, and `answer_type_check`.

## Answer normalization

Return exact rational values first; label approximations and state error sign,
norm, or spectral-radius convention.

## Trace step guidance

Expose formula, exact computation, error/stability theorem, check, and final
normalized number.
