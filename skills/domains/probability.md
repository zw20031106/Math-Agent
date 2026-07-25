---
name: probability
subject: probability
kind: domain
version: 2.0
triggers: probability, random variable, expectation, variance, conditional distribution, 概率, 随机变量, 期望, 方差
roles: PrimarySolver, AlternativeSolver, VerifierSkeptic, RepairAgent
---
## Triggers

Random variables, distributions, conditioning/Bayes, order statistics,
expectations, variances, and finite random walks.

## Roles

Solvers use conditioning, indicators, or distribution transforms; Verifier
checks support and normalization; Repair fixes local probability Claims.

## Method decision tree

Condition on a sufficient count/state, use indicator linearity for sums, derive
a density/CDF for transforms or order statistics, and exploit named
distribution identities only with parameters fixed.

## Theorem preconditions

State support, parameter convention, independence/conditional independence,
conditioning event of positive probability, and integrability for moments.

## Common errors

Do not confuse rate/scale, second largest/second smallest, conditional and
unconditional variance, or sampling with/without replacement.

## Counterexample checklist

Check probabilities sum to one, supports/endpoints, zero counts, extreme
parameters, and independent versus dependent alternatives.

## Compatible check types

Use `reasoning`, `symbolic_equivalence`, `boundary`,
`theorem_preconditions`, and `answer_type_check`.

## Answer normalization

Return exact probabilities/fractions and clearly label conditional events,
moments, or distribution parameters.

## Trace step guidance

Expose support/conditioning, distribution identity, exact calculation,
normalization check, and result.
