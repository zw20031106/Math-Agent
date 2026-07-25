---
name: proof-obligation
subject: general-math
kind: general
version: 2.0
triggers: proof, derivation, iff, existence, uniqueness, 证明, 推导
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
---
## Triggers

Use for proof and derivation tasks and whenever theorem directions,
existence/uniqueness, or interchange conditions are material.

## Roles

Solvers create obligations, LemmaCurator preserves them, Verifier classifies
them, and Repair patches only failed closures.

## Method decision tree

List definitions, theorem hypotheses, required directions, construction,
boundary cases, existence, uniqueness, and interchange before concluding.

## Theorem preconditions

Every invoked theorem must name and discharge its hypotheses at the relevant
Claim, not only in a global assumptions list.

## Common errors

Do not prove only necessity, assume existence while proving uniqueness, ignore
degenerate cases, or treat a checked example as a universal proof.

## Counterexample checklist

Negate each required conclusion, test missing hypotheses, and inspect equality
and degenerate boundaries.

## Compatible check types

Use `definition`, `theorem_preconditions`, `necessity`, `sufficiency`,
`existence`, `uniqueness`, `boundary`, and `interchange`.

## Answer normalization

The final conclusion must match the exact requested proposition and quantify
all variables.

## Trace step guidance

Map each public Claim and MethodStep to obligation IDs and expose unresolved
obligations explicitly.
