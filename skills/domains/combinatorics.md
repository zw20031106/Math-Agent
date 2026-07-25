---
name: combinatorics
subject: combinatorics
kind: domain
version: 2.0
triggers: counting, permutation, combination, bijection, recurrence, 计数, 排列, 组合
roles: PrimarySolver, AlternativeSolver, VerifierSkeptic, RepairAgent
---
## Triggers

Finite counting, permutations/combinations, bijections, recurrences, generating
functions, invariants, and extremal arguments.

## Roles

Solvers construct counts; Verifier checks disjointness and multiplicity;
Repair fixes local overcount Claims.

## Method decision tree

Define the counted set, then choose a bijection, recurrence/generating
function, inclusion-exclusion, or invariant/extremal argument.

## Theorem preconditions

Check finiteness, labeled/unlabeled conventions, replacement, order,
independence of choices, and recurrence base cases.

## Common errors

Do not double-count overlapping cases, omit symmetry divisors, or use a
recurrence without sufficient initial values.

## Counterexample checklist

Enumerate the smallest sizes, inspect empty/singleton cases, symmetry-fixed
objects, and case-partition overlap.

## Compatible check types

Use `reasoning`, `definition`, `boundary`, `necessity`, and `sufficiency`.

## Answer normalization

Return exact integers or coefficient formulas with valid parameter ranges.

## Trace step guidance

Expose the counted objects, partition/bijection, base cases, correction, and
exact count.
