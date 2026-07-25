---
name: advanced-real-analysis
subject: advanced-real-analysis
kind: domain
version: 2.0
triggers: limit, improper integral, series, power series, convergence, 极限, 积分, 级数
roles: PrimarySolver, AlternativeSolver, VerifierSkeptic, RepairAgent
---
## Triggers

Limits, infinite series, improper integrals, power series, inverse
differentiation, convergence modes, and supremum norms.

## Roles

Solvers provide analytic estimates or transformations; Verifier checks limit
interchanges and domination; Repair fixes failed conditions locally.

## Method decision tree

Try exact expansion or identity, then change variables, dominated/monotone
convergence, comparison estimates, and asymptotic remainder bounds.

## Theorem preconditions

State domains, convergence radius, uniformity, domination, integrability,
differentiability order, endpoint behavior, and branch choices.

## Common errors

Do not interchange limits and sums without a theorem, ignore improper
endpoints, truncate asymptotics too early, or differentiate an inverse at the
wrong point.

## Counterexample checklist

Check endpoints, nonuniform convergence, sign-changing domination, divergent
tails, zero derivatives, and equality cases.

## Compatible check types

Use `reasoning`, `interchange`, `boundary`, `symbolic_equivalence`,
`simplify_expression`, and `theorem_preconditions`.

## Answer normalization

Preserve exact constants, convergence intervals with endpoint status, and
explicit limiting values.

## Trace step guidance

Expose the analytic identity or estimate, theorem conditions, limiting
operation, and exact answer.
