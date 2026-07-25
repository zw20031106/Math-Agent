---
name: lemma-compression
subject: general-math
kind: general
version: 2.0
triggers: deep proof, reusable claim, dependency closure, lemma, 引理
roles: LemmaCurator
---
## Triggers

Use only in high-risk proof or derivation routes where a verified local Claim
can shorten later dependencies.

## Roles

LemmaCurator is a deterministic Host role and never requests private reasoning.

## Method decision tree

Select a public Claim, close its dependencies, copy every required condition,
attach evidence, and reject duplicates or conflicted statements.

## Theorem preconditions

A lemma is reusable only under conditions at least as strong as its source and
after its source Claim has acceptable verification state.

## Common errors

Do not generalize scope, omit quantifiers, treat numerical support as proof, or
reuse a rejected lemma.

## Counterexample checklist

Check whether weakening a copied condition breaks the statement and whether a
dependency is hidden in notation.

## Compatible check types

Use `reasoning`, `theorem_preconditions`, `necessity`, `sufficiency`,
`existence`, `uniqueness`, and `boundary`.

## Answer normalization

Keep lemma notation consistent with the original problem and namespace all
source Claim references.

## Trace step guidance

Record statement, conditions, source Claims, evidence status, downstream use,
and re-verification outcome.
