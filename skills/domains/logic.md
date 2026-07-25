---
name: logic
subject: logic
kind: domain
version: 2.0
triggers: proposition, predicate, quantifier, model, 命题, 谓词, 量词
roles: PrimarySolver, AlternativeSolver, VerifierSkeptic, RepairAgent
---
## Triggers

Propositions, predicates, quantifiers, validity, satisfiability, derivations,
models, and countermodels.

## Roles

Solvers use deduction, contradiction, or model construction; Verifier checks
scope and semantics; Repair fixes local inference Claims.

## Method decision tree

Normalize quantifiers/connectives, use direct deduction for derivability,
contradiction for inconsistency, and a concrete model/countermodel for semantic
claims.

## Theorem preconditions

Check variable scope, free/bound status, inference-system rules, domain
nonemptiness, and semantic versus syntactic targets.

## Common errors

Do not swap quantifiers, affirm the consequent, conflate consistency with
truth, or use a semantic argument for a syntactic claim without completeness.

## Counterexample checklist

Use the smallest finite domains and truth assignments; test vacuous truth and
empty relations.

## Compatible check types

Use `reasoning`, `definition`, `necessity`, `sufficiency`, and
`theorem_preconditions`.

## Answer normalization

State the formula, truth/validity status, derivation conclusion, or explicit
countermodel.

## Trace step guidance

Expose normalized formula, rule/model, scoped inference, countercheck, and
conclusion.
