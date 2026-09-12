---
name: eigenvalue-diagonalization
version: 3.0
domain: linear_algebra
subdomain: linear map
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: eigenvalue, diagonalizable, eigenvector
problem_patterns: diagonalize matrix, spectrum
method_family: eigenvalue-diagonalization
alternative_skills: jordan-form
description: Diagonalize a finite-dimensional operator only when eigenvectors form a basis over the stated scalar field.
negative_triggers: unavailable exact roots, ambiguous scalar field, one eigenvector for a repeated root
required_observables: scalar field, characteristic polynomial, eigenspace dimensions
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Recognition
Use when the target asks for a basis P and diagonal D with AP=PD or asks whether a matrix is diagonalizable.

## Do Not Use When
Do not infer diagonalizability from a complete list of eigenvalues, a numerical eigensolver, or a rectangular matrix. The scalar field and exact eigenspace dimensions are decisive.

## Core Theorem
A finite-dimensional operator is diagonalizable over F exactly when the direct sum of its eigenspaces has dimension equal to the space, equivalently when a basis of eigenvectors exists over F.

## Exact Preconditions
State F and the vector-space dimension. Factor the characteristic polynomial over F, compute each eigenspace dimension, and verify the total geometric multiplicity equals the dimension. For an explicit P, prove det(P)≠0.

## Procedure
1. Compute the characteristic polynomial and its roots over F.
2. Solve (A−λI)v=0 for a basis in each eigenspace.
3. Count independent eigenvectors and assemble P and D.
4. Verify P is invertible and AP=PD exactly, with all domain/field assumptions recorded.

## Branch Conditions
Handle repeated roots, complex field extensions, and the nondiagonalizable case separately. Distinct roots are sufficient but not necessary.

## Failure Modes
Replacing geometric multiplicity by algebraic multiplicity, using approximate roots as exact, or skipping P invertibility invalidates the similarity claim.

## Counterexample Patterns
Test a single Jordan block: its repeated eigenvalue has algebraic multiplicity two but only one independent eigenvector.

## Verification Recipe
Use `symbolic_equivalence` to check AP=PD and determinant identities only under the stated field/domain assumptions. A symbolic equality does not prove that P exists or is invertible; the proof trace must close the eigenspace-basis obligation.

## Mini Example
diag(2,3) is already diagonal over the reals with P=I and two independent standard eigenvectors.

## Alternative Strategy
Use Jordan form when the eigenspaces do not span, or the spectral theorem when symmetry/Hermiticity supplies an orthonormal basis.

## Stop / Escalate Conditions
Escalate when roots are unavailable over F, eigenspace dimensions are unresolved, or det(P) is not certified. Do not promote approximate numerical diagonalization to an exact result.

