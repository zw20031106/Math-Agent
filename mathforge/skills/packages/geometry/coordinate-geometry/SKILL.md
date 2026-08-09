---
name: coordinate-geometry
version: 3.0
domain: geometry
subdomain: geometry
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: coordinates, slope, distance
problem_patterns: analytic geometry, locus
method_family: coordinate-geometry
alternative_skills: synthetic-similarity
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Recognition
Use when the problem exposes analytic geometry, locus.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
Coordinate placement preserves the relevant Euclidean incidences when chosen by a rigid or similarity normalization.

## Exact Preconditions
The coordinate system avoids collapsing distinct points.

## Procedure
Choose simple axes translate constraints to equations solve then interpret geometrically.

## Branch Conditions
Branch for vertical lines and sign choices from squared distances.

## Failure Modes
Squaring distance equations may introduce mirror branches.

## Counterexample Patterns
Substitute solutions into unsquared geometric constraints.

## Verification Recipe
Verify incidence distance and orientation conditions.

## Mini Example
Place a circle center at origin to use x^2+y^2=r^2.

## Alternative Strategy
Use synthetic similarity or vectors.

## Stop / Escalate Conditions
Escalate when coordinates create high-degree extraneous branches.
