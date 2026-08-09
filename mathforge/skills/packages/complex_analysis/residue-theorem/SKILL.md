---
name: residue-theorem
version: 3.0
domain: complex_analysis
subdomain: integration
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: residue, contour integral, pole
problem_patterns: complex contour integral, meromorphic
method_family: residue-theorem
alternative_skills: laurent-classification
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Recognition
Use when the problem exposes complex contour integral, meromorphic.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
A positively oriented contour integral equals 2pi i times enclosed residues when no singularity lies on the contour.

## Exact Preconditions
Meromorphicity orientation and contour singularity exclusions are established.

## Procedure
Locate singularities classify enclosed poles compute residues and sum.

## Branch Conditions
Branch by contour orientation and parameter-dependent pole location.

## Failure Modes
A pole on the contour invalidates the ordinary theorem.

## Counterexample Patterns
Test boundary poles and orientation reversal.

## Verification Recipe
Compare with a direct parameterization for a simple contour.

## Mini Example
Integral around |z|=2 of 1/z is 2pi i.

## Alternative Strategy
Use Cauchy integral formula or deformation.

## Stop / Escalate Conditions
Escalate for branch points or contour singularities.
