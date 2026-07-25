---
name: set-theory
subject: set-theory
kind: domain
version: 2.0
triggers: set theory, cardinality, power set, relation, 集合, 基数, 幂集
roles: PrimarySolver, AlternativeSolver, VerifierSkeptic, RepairAgent
---
## Triggers

Sets, power sets, cardinality, relations, set operations, and set-theoretic
constructions outside topology.

## Roles

Solvers use inclusions/bijections; Verifier checks universes and element types;
Repair fixes local set Claims.

## Method decision tree

For equality prove both inclusions; for cardinality construct a bijection or
count subsets; for relations check definition and closure properties.

## Theorem preconditions

State the universe, finite/infinite setting, choice assumptions if material,
and exact element predicates.

## Common errors

Do not confuse element/subset, set/list order, union/intersection, or injective
with bijective.

## Counterexample checklist

Test empty/singleton sets, duplicate representations, boundary predicates, and
failure of one inclusion.

## Compatible check types

Use `reasoning`, `definition`, `necessity`, `sufficiency`, and `boundary`.

## Answer normalization

Use braces/set-builder notation and exact cardinal numbers or integers.

## Trace step guidance

Expose universe, inclusion/bijection, edge cases, and normalized set/count.
