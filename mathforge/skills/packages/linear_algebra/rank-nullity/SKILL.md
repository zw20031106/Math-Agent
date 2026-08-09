---
name: rank-nullity
version: 3.0
domain: linear_algebra
subdomain: linear map
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: rank, nullity, dimension kernel
problem_patterns: kernel dimension, image dimension
method_family: rank-nullity
alternative_skills: gaussian-elimination
requires: matrix_shape_check
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: matrix_shape_check
---
## Recognition
Use when the problem exposes kernel dimension, image dimension.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
For a linear map on a finite-dimensional domain, rank plus nullity equals domain dimension.

## Exact Preconditions
Linearity and finite dimension are established.

## Procedure
Compute pivots for rank and solve the homogeneous system for nullity.

## Branch Conditions
Branch by parameter-dependent pivot structure.

## Failure Modes
Using codomain dimension instead of domain dimension is incorrect.

## Counterexample Patterns
Check the zero map and injective maps.

## Verification Recipe
Verify independent kernel basis vectors and pivot count.

## Mini Example
A 2 by 3 rank-2 matrix has nullity 1.

## Alternative Strategy
Use basis extension or quotient spaces.

## Stop / Escalate Conditions
Escalate when the spaces are infinite-dimensional.
