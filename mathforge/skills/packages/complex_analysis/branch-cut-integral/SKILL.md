---
name: branch-cut-integral
version: 3.0
domain: complex_analysis
subdomain: integration
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: branch cut, keyhole contour, log branch
problem_patterns: multivalued complex function, contour integral
method_family: branch-cut-integral
alternative_skills: residue-theorem
requires: numerical_residual
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: numerical_residual
---
## Recognition
Use when the problem exposes multivalued complex function, contour integral.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
A branch of logarithm or power is analytic only after a consistent cut and argument range are fixed.

## Exact Preconditions
The branch domain contour and jump across the cut are explicit.

## Procedure
Choose the cut parameterize both banks account for orientation then take boundary limits.

## Branch Conditions
Branch by argument convention and endpoint indentation.

## Failure Modes
Using inconsistent arguments on two banks corrupts the jump factor.

## Counterexample Patterns
Test integer exponents where the jump disappears.

## Verification Recipe
Track each contour segment and verify vanishing arcs.

## Mini Example
A keyhole contour turns z^a into factors differing by e^{2pi i a}.

## Alternative Strategy
Use real substitutions or residues without branches.

## Stop / Escalate Conditions
Escalate when endpoints are nonintegrable or arcs do not vanish.
