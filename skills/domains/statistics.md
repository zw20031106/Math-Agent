---
name: statistics
subject: statistics
kind: domain
version: 2.0
triggers: likelihood, estimator, Fisher information, Cramer-Rao, sufficient statistic, 统计推断, 最大似然, 估计量
roles: PrimarySolver, AlternativeSolver, VerifierSkeptic, RepairAgent
---
## Triggers

Likelihood, estimators, Fisher information, Cramér–Rao bounds, sufficiency,
sampling distributions, and parameter inference.

## Roles

Solvers derive likelihood/information; Verifier checks model and regularity;
Repair fixes local derivative or parameter Claims.

## Method decision tree

Write the joint log-likelihood, differentiate under the stated
parameterization, check boundaries, compute information by score variance or
expected Hessian, and apply lower bounds only to the target function.

## Theorem preconditions

State iid assumptions, support dependence, parameter domain, rate/scale
convention, unbiasedness, differentiability, and regularity for exchanging
derivative/integral.

## Common errors

Do not use unbiased sample variance as the normal-model MLE, confuse total and
per-observation information, or omit the derivative of a transformed target.

## Counterexample checklist

Check boundary MLEs, support depending on parameters, zero variance, sample
size factors, and identifiability.

## Compatible check types

Use `reasoning`, `symbolic_equivalence`, `interchange`,
`theorem_preconditions`, and `answer_type_check`.

## Answer normalization

Return estimators as functions/data values and information/bounds as exact
nonnegative scalars with sample-size dependence.

## Trace step guidance

Expose model/parameterization, likelihood or score, regularity, calculation,
and normalized estimate/bound.
