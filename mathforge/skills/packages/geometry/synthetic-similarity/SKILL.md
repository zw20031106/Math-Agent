---
name: synthetic-similarity
version: 3.0
domain: geometry
subdomain: geometry
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: similar triangles, angle chase, ratio
problem_patterns: triangle similarity, geometric ratios
method_family: synthetic-similarity
alternative_skills: coordinate-geometry
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Recognition
Use when the problem exposes triangle similarity, geometric ratios.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
AA SAS or SSS similarity transfers corresponding ratios and angles.

## Exact Preconditions
Corresponding vertices and nondegenerate triangles are identified.

## Procedure
Establish a valid criterion then write ratios in matched order.

## Branch Conditions
Branch for direct and oppositely oriented similarity.

## Failure Modes
Visual appearance does not prove correspondence.

## Counterexample Patterns
Test degenerate or swapped-vertex cases.

## Verification Recipe
Check angle equalities and cross-multiply claimed ratios.

## Mini Example
Two AA-matched triangles have proportional sides.

## Alternative Strategy
Use coordinates or vectors.

## Stop / Escalate Conditions
Escalate when a needed angle equality is unproved.
