---
name: complex-analysis
subject: complex-analysis
kind: domain
version: 2.0
triggers: contour, residue, holomorphic, Rouché, analytic continuation, 留数, 复分析
roles: PrimarySolver, AlternativeSolver, VerifierSkeptic, RepairAgent
---
## Triggers

Contours, residues, poles, Rouché counting, Taylor/Laurent coefficients,
entire functions, analytic continuation, and real integrals by residues.

## Roles

Solvers choose residue, coefficient, or zero-counting methods; Verifier checks
contours and hypotheses; Repair fixes local singularity or branch Claims.

## Method decision tree

Locate/classify singularities, choose Cauchy/residue formulas for integrals,
compare strict boundary magnitudes for Rouché, and use Laurent coefficients for
infinity or high-order poles.

## Theorem preconditions

State contour orientation, enclosed singularities, branch cuts, analyticity on
the contour, pole order, and decay on auxiliary arcs.

## Common errors

Do not include poles outside the contour, miss derivative factors at repeated
poles, use non-strict Rouché bounds, or confuse the residue at infinity sign.

## Counterexample checklist

Check contour-boundary zeros, branch points, pole cancellation, orientation,
arc decay, and the sum of finite plus infinite residues.

## Compatible check types

Use `symbolic_equivalence`, `reasoning`, `theorem_preconditions`, `boundary`,
and `latex_syntax_check`.

## Answer normalization

Preserve exact multiples of \(2\pi i\), integer zero counts, exact
coefficients, and explicit complex values.

## Trace step guidance

Expose singularities/contour, theorem conditions, residue or comparison
calculation, and exact result.
