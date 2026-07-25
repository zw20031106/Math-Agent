---
name: calculus
subject: calculus
kind: domain
version: 2.0
triggers: derivative, integral, limit, maximum, minimum, 导数, 积分, 极限
roles: PrimarySolver, AlternativeSolver, VerifierSkeptic, RepairAgent
---
## Triggers

Elementary differentiation, integration, limits, extrema, and change of
variables.

## Roles

Solvers compute and justify; Verifier checks domains/endpoints; Repair corrects
local derivative or integral Claims.

## Method decision tree

Use a direct identity, substitution/integration by parts, local expansion, or
stationarity plus endpoint comparison.

## Theorem preconditions

Check differentiability, continuity, substitution monotonicity, improper
convergence, interior versus boundary extrema, and interchange hypotheses.

## Common errors

Do not omit constants, ignore endpoints, substitute incorrect bounds, or infer
a global extremum from a stationary point alone.

## Counterexample checklist

Differentiate the antiderivative, test endpoints and singularities, compare
one-sided limits, and verify dimensions/sign.

## Compatible check types

Use `symbolic_equivalence`, `reasoning`, `boundary`, `interchange`, and
`theorem_preconditions`.

## Answer normalization

Keep exact constants and clearly label definite values, intervals, or
extremizers.

## Trace step guidance

Expose the chosen identity, conditions, calculation, endpoint check, and exact
answer.
