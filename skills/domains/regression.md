---
name: regression
subject: regression
kind: domain
version: 2.0
triggers: linear regression, least squares, ridge, hat matrix, residual, F statistic, 线性回归, 最小二乘
roles: PrimarySolver, AlternativeSolver, VerifierSkeptic, RepairAgent
---
## Triggers

Normal equations, centered designs, least squares, ridge regression, leverage,
leave-one-out residuals, nested-model partial \(F\) tests.

## Roles

Solvers use row-space or convex quadratic methods; Verifier checks dimensions
and degrees of freedom; Repair corrects local matrix/statistic Claims.

## Method decision tree

Solve \(X^TX\beta=X^Ty\), add \(\lambda I\) for ridge under the stated
intercept convention, use \(e_i/(1-h_{ii})\) for LOOCV, and form the partial
\(F\) ratio with the full-model residual degrees of freedom.

## Theorem preconditions

Check centering/intercept treatment, full rank or chosen generalized inverse,
penalty convention, nested models, sample size, and parameter counts.

## Common errors

Do not penalize an intercept silently, reverse reduced/full RSS, use the wrong
degrees of freedom, or treat \(X^TX\) as \(XX^T\).

## Counterexample checklist

Check singular design, \(\lambda=0\), leverage one, nonnested models, vector
shape, and coefficient ordering.

## Compatible check types

Use `matrix_shape_check`, `symbolic_equivalence`, `reasoning`,
`theorem_preconditions`, and `answer_type_check`.

## Answer normalization

Return coefficients as an ordered exact vector and statistics as exact
fractions before optional decimals.

## Trace step guidance

Expose matrix equation, dimensions, inversion/statistic calculation, checks,
and normalized vector or scalar.
