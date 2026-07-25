---
name: abstract-algebra
subject: abstract-algebra
kind: domain
version: 2.0
triggers: group, ring, field, ideal, homomorphism, 群, 环, 域, 理想
roles: PrimarySolver, AlternativeSolver, VerifierSkeptic, RepairAgent
---
## Triggers

Finite groups and fields, quotient rings, ideals, homomorphisms, conjugacy,
Sylow theory, and irreducible polynomials.

## Roles

Solvers choose a structural or counting route; Verifier and Repair check local
algebraic hypotheses and closure.

## Method decision tree

Identify the algebraic category, reduce finite counts by structure theorems,
use factorization for rings/fields, and use orbit or Sylow constraints for
groups.

## Theorem preconditions

Check finiteness, normality, commutativity, field characteristic, monicity,
coprimality, and whether an action is well defined.

## Common errors

Do not confuse element order with group order, count non-surjective maps as
surjective, or use Chinese remainder decomposition without coprime ideals.

## Counterexample checklist

Test the identity, zero divisors, nonnormal subgroups, repeated factors, and
small characteristics.

## Compatible check types

Use `reasoning`, `definition`, `theorem_preconditions`, `necessity`,
`sufficiency`, and finite-case `reasoning`.

## Answer normalization

Return exact counts, invariant-factor notation, or a named algebraic structure
with its operation and modulus.

## Trace step guidance

Expose the structure theorem, verified hypotheses, counting formula, and exact
result as public steps.
