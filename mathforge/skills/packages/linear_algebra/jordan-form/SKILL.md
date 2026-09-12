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
description: Determine Jordan block sizes from generalized eigenspaces over a field where the characteristic polynomial splits.
negative_triggers: nonsplitting field, shape check only, algebraic multiplicity alone
required_observables: scalar field, characteristic roots, kernel dimensions
requires: matrix_shape_check
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: matrix_shape_check
---
## Recognition
Use when a linear operator may be nondiagonalizable and the target asks for Jordan blocks, generalized eigenvectors, or nilpotent indices.

## Do Not Use When
Do not infer block structure from matrix dimensions or algebraic multiplicities alone. If the characteristic polynomial does not split over the stated field, ordinary Jordan form over that field is unavailable.

## Core Theorem
Over a splitting field, the generalized eigenspace ker(A−λI)^k stabilizes, and the increments in its dimensions determine the numbers and sizes of Jordan blocks for λ. A Jordan basis records chains, not just eigenvalues.

## Exact Preconditions
State the finite-dimensional vector space and scalar field; prove the characteristic polynomial splits (or extend the field explicitly). For every eigenvalue, compute enough nullities of (A−λI)^k to reach the stabilized generalized eigenspace and track algebraic multiplicity.

## Procedure
1. Compute and factor the characteristic polynomial over the stated field.
2. Find dim ker(A−λI)^k for each λ until stabilization.
3. Recover block counts from successive nullity differences.
4. Construct chains whose lengths match those counts and verify that the chain vectors form a basis.
5. Reconstruct A in the chain basis and compare the block multiplicities.

## Branch Conditions
Treat each eigenvalue independently, distinguish diagonalizable blocks of size one from longer chains, and switch to rational canonical form over a nonsplitting field.

## Failure Modes
Using algebraic multiplicity as geometric multiplicity, stopping before kernel stabilization, or mixing fields produces the wrong blocks. A rectangular matrix is not evidence of a valid similarity transform.

## Counterexample Patterns
Compare I, a diagonal matrix with a repeated eigenvalue, and [[1,1],[0,1]]; they share an eigenvalue but have different eigenspace dimensions and block structures.

## Verification Recipe
`matrix_shape_check` verifies only rectangular dimensions and is not a Jordan proof. Use it as a structural precheck; the Verifier must check chain relations, basis independence, field splitting, and block reconstruction in the proof trace.

## Mini Example
For A=[[1,1],[0,1]], dim ker(A−I)=1 and dim ker(A−I)^2=2, so there is one Jordan block of size two.

## Alternative Strategy
Use rational canonical form when splitting fails, or use eigenvalue diagonalization when every generalized eigenspace is already spanned by eigenvectors.

## Stop / Escalate Conditions
Escalate when the field, factorization, nullity sequence, or chain-basis independence is unresolved. Do not close the result from a shape check.

