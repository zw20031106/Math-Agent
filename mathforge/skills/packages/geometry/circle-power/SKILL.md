---
name: circle-power
version: 3.0
domain: geometry
subdomain: geometry
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: power of a point, secant, tangent
problem_patterns: circle secant product, radical axis
method_family: circle-power
alternative_skills: synthetic-similarity
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Recognition
Use when the problem exposes circle secant product, radical axis.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
For a fixed circle directed secant products equal the point power; tangent length squared is the power.

## Exact Preconditions
Directed-length convention and point location are explicit.

## Procedure
Identify two secants or a tangent then equate directed products.

## Branch Conditions
Branch for points inside and outside the circle.

## Failure Modes
Unsigned lengths can hide a negative inside power.

## Counterexample Patterns
Test a point on the circle and an internal point.

## Verification Recipe
Check products using a coordinate circle model.

## Mini Example
PA*PB=PC*PD for two secants through P.

## Alternative Strategy
Use similar triangles or coordinates.

## Stop / Escalate Conditions
Escalate when segment orientation is ambiguous.
