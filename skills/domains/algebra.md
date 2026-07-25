---
name: algebra
subject: algebra
kind: domain
version: 2.0
triggers: equation, inequality, polynomial, 方程, 不等式, 多项式
roles: PrimarySolver, AlternativeSolver, VerifierSkeptic, RepairAgent
---
## Triggers

Elementary equations, inequalities, polynomial manipulation, factorization,
and algebraic identities.

## Roles

Solvers transform expressions; Verifier checks equivalence and excluded cases;
Repair corrects failed transformations.

## Method decision tree

Simplify domains first, then choose substitution/elimination, factorization and
invariants, or a structure-preserving transform.

## Theorem preconditions

Track nonzero denominators, signs before inequality operations, real/complex
domains, and reversibility of roots, powers, logarithms, and exponentials.

## Common errors

Do not cancel possible zeros, introduce extraneous roots, flip an inequality
incorrectly, or divide by an expression of unknown sign.

## Counterexample checklist

Test excluded roots, zeros of factors, equality boundaries, sign changes, and
parameters where degree drops.

## Compatible check types

Use `symbolic_equivalence`, `simplify_expression`,
`safe_parse_expression`, `reasoning`, and `boundary`.

## Answer normalization

Return exact roots/sets or a canonical polynomial and state all restrictions.

## Trace step guidance

Expose each reversible transformation, excluded case, verification Claim, and
exact answer.
