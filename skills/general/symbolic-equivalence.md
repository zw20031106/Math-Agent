---
name: symbolic-equivalence
subject: general-math
kind: general
version: 2.0
triggers: expression, polynomial, identity, equivalent, 表达式, 恒等式
roles: PrimarySolver, AlternativeSolver, VerifierSkeptic
---
## Triggers

Use for expression or polynomial answers, algebraic identities, transformed
equations, and comparison of candidate forms.

## Roles

Solvers provide equality Claims; Verifier checks whether supplied evidence
supports equality under the declared domain.

## Method decision tree

Normalize notation, declare domains, move both sides to one expression,
factor/simplify exactly, and separately track transformations that are not
reversible.

## Theorem preconditions

Denominators must be nonzero; branch, sign, and domain restrictions must be
preserved through roots, logarithms, powers, and inverse functions.

## Common errors

Do not cancel a zero factor, square without checking extraneous roots, compare
floating decimals as exact, or ignore branch choices.

## Counterexample checklist

Test excluded roots, zeros of cancelled factors, negative inputs, complex
branches, endpoints, and singular parameter values.

## Compatible check types

Use `safe_parse_expression`, `symbolic_equivalence`,
`simplify_expression`, or `reasoning`.

## Answer normalization

Prefer a canonical exact form while retaining conditions that make equivalent
forms valid.

## Trace step guidance

Expose the equality Claim, domain assumptions, reversible transformation, and
Host evidence outcome.
