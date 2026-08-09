---
name: jordan-form
version: 3.0
domain: linear_algebra
subdomain: linear map
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: jordan, generalized eigenvector, nilpotent
problem_patterns: nondiagonalizable matrix, Jordan blocks
method_family: jordan-form
alternative_skills: eigenvalue-diagonalization
requires: matrix_shape_check
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: matrix_shape_check
---
## Recognition
Use when the problem exposes nondiagonalizable matrix, Jordan blocks.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
Jordan chains encode kernels of successive powers of A-lambda I over a splitting field.

## Exact Preconditions
The characteristic polynomial splits over the chosen field.

## Procedure
Compute eigenvalues then nullities of successive powers to infer block sizes.

## Branch Conditions
Branch by each eigenvalue independently.

## Failure Modes
Algebraic multiplicity alone does not determine block sizes.

## Counterexample Patterns
Test a repeated eigenvalue with different eigenspace dimensions.

## Verification Recipe
Reconstruct chain relations and block multiplicities.

## Mini Example
[[1,1],[0,1]] is one size-2 Jordan block.

## Alternative Strategy
Use rational canonical form over nonsplitting fields.

## Stop / Escalate Conditions
Escalate when the field does not contain all eigenvalues.
