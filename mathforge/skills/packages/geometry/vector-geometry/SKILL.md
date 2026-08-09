---
name: vector-geometry
version: 3.0
domain: geometry
subdomain: geometry
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: vector, dot product, cross product
problem_patterns: angles distances parallelism
method_family: vector-geometry
alternative_skills: coordinate-geometry
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Recognition
Use when the problem exposes angles distances parallelism.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
Dot products encode lengths and angles while linear dependence encodes parallelism.

## Exact Preconditions
Vectors share a common affine origin convention.

## Procedure
Translate points to displacement vectors and impose dot or determinant relations.

## Branch Conditions
Branch for zero vectors and dimension-specific cross products.

## Failure Modes
Position vectors and displacement vectors are not interchangeable.

## Counterexample Patterns
Test coincident points and reversed orientation.

## Verification Recipe
Translate the final vector statement back to geometry.

## Mini Example
Perpendicular u and v satisfy u dot v=0.

## Alternative Strategy
Use coordinates or synthetic geometry.

## Stop / Escalate Conditions
Escalate when orientation or dimension is unspecified.
