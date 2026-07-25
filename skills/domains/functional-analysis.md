---
name: functional-analysis
subject: functional-analysis
kind: domain
version: 2.0
triggers: Banach, Hilbert, operator, spectrum, functional, 算子, 谱, 泛函
roles: PrimarySolver, AlternativeSolver, VerifierSkeptic, RepairAgent
---
## Triggers

Banach/Hilbert spaces, bounded functionals, operator spectra and norms,
projections, shifts, compact or integral operators.

## Roles

Solvers choose spectral, geometric, or duality arguments; Verifier checks space
and boundedness hypotheses; Repair patches failed operator Claims.

## Method decision tree

Use orthogonal projection for distances, dual norms for functionals,
eigenvalue/resolvent analysis for spectra, and variational characterizations
for compact self-adjoint operators.

## Theorem preconditions

Name the ambient normed space, scalar field, boundedness, completeness,
self-adjointness, compactness, and closure of subspaces.

## Common errors

Do not identify spectrum with eigenvalues in infinite dimensions, omit zero
from a compact spectrum, or use an inner product formula in a Banach space.

## Counterexample checklist

Test zero, approximate eigenvectors, nonclosed ranges, nonattained suprema, and
complex versus real scalars.

## Compatible check types

Use `reasoning`, `definition`, `theorem_preconditions`, `boundary`, and
`symbolic_equivalence` for finite algebraic reductions.

## Answer normalization

State spectra as sets, distances and norms as exact nonnegative scalars, and
operator conventions explicitly.

## Trace step guidance

Expose the space, operator property, theorem, spectral/norm calculation, and
final normalized object.
