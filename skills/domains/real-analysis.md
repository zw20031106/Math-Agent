---
name: real-analysis
subject: real-analysis
kind: domain
version: 2.0
triggers: real analysis, uniform convergence, compactness, completeness, measure
roles: PrimarySolver, AlternativeSolver, VerifierSkeptic, RepairAgent
---
## Triggers

English/general real-analysis wording, convergence modes, compactness,
completeness, and continuity arguments.

## Roles

Solvers use direct analytic estimates; Verifier checks quantifiers and theorem
hypotheses; Repair fixes local analytic Claims.

## Method decision tree

Write quantifiers, choose epsilon estimates, compactness/subsequence,
completeness/Cauchy, or uniform convergence as the target requires.

## Theorem preconditions

Check metric/normed space, completeness, compactness, continuity, uniformity,
measurability, and domination.

## Common errors

Do not swap pointwise/uniform convergence, infer compactness from boundedness in
infinite dimensions, or move quantifiers.

## Counterexample checklist

Test endpoint sequences, moving spikes, incomplete spaces, nonuniform
subsequences, and failure of domination.

## Compatible check types

Use `reasoning`, `interchange`, `boundary`, `theorem_preconditions`,
`necessity`, and `sufficiency`.

## Answer normalization

State convergence mode, domain, constants, and exact limiting object.

## Trace step guidance

Expose quantifiers, theorem conditions, estimate/subsequence, boundary check,
and conclusion.
