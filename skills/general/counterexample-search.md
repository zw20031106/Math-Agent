---
name: counterexample-search
subject: general-math
kind: general
version: 2.0
triggers: universal claim, missing condition, boundary, counterexample, 反例
roles: VerifierSkeptic
---
## Triggers

Use for medium/high-risk candidates, universal statements, converse claims, and
findings with missing hypotheses.

## Roles

VerifierSkeptic challenges public Claims and Proof Obligations only.

## Method decision tree

Test the smallest admissible objects, then zero/one, boundaries, degeneracies,
sign changes, symmetry-breaking cases, and finally a structured family.

## Theorem preconditions

A proposed counterexample must satisfy every original domain and side
condition; otherwise it only identifies a missing-condition question.

## Common errors

Do not use an inadmissible value, numerical noise, a changed convention, or a
case excluded by the problem.

## Counterexample checklist

Check empty and singleton objects, equality boundaries, singular matrices,
zero-probability events, disconnected cases, and nonunique optimizers.

## Compatible check types

Use `reasoning`, `boundary`, `necessity`, `sufficiency`, or
`symbolic_equivalence` as Host check suggestions.

## Answer normalization

State a counterexample with all parameters and its violated Claim; otherwise
return an explicit unresolved condition rather than a false disproof.

## Trace step guidance

Expose only the tested public case, the Claim ID, conditions, and outcome.
