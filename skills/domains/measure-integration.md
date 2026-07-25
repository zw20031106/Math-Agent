---
name: measure-integration
subject: measure-integration
kind: domain
version: 2.0
triggers: Lebesgue, measure, Tonelli, Fubini, Lp, indicator, 测度, 可积
roles: PrimarySolver, AlternativeSolver, VerifierSkeptic, RepairAgent
---
## Triggers

Lebesgue measure, measurable functions, \(L^p\) norms, indicator sequences,
Tonelli/Fubini, dominated convergence, and singular double integrals.

## Roles

Solvers select a convergence or integration theorem; Verifier checks
measurability and hypotheses; Repair restores omitted local conditions.

## Method decision tree

For nonnegative integrands use Tonelli/monotone convergence; for signed
integrands establish absolute integrability before Fubini; for limits seek
domination or uniform integrability.

## Theorem preconditions

Check measure spaces, measurability, nonnegativity, sigma-finiteness where
needed, integrable domination, and almost-everywhere statements.

## Common errors

Do not swap integrals for conditionally integrable functions, confuse pointwise
and norm convergence, or ignore null-set equivalence.

## Counterexample checklist

Check singular diagonals, shrinking supports, nonintegrable dominators,
infinite measure, and endpoints of \(p\)-integrability.

## Compatible check types

Use `reasoning`, `interchange`, `boundary`, `theorem_preconditions`, and
`symbolic_equivalence` for exact integral reductions.

## Answer normalization

Return exact measures, norms, and integrals; state infinity or almost-everywhere
qualifiers explicitly.

## Trace step guidance

Expose measurability/nonnegativity, theorem hypotheses, interchanged operation,
and exact result.
