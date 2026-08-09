---
name: laurent-classification
version: 3.0
domain: complex_analysis
subdomain: analysis
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: laurent, isolated singularity, principal part
problem_patterns: classify singularity, annulus expansion
method_family: laurent-classification
alternative_skills: residue-theorem
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Recognition
Use when the problem exposes classify singularity, annulus expansion.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
The Laurent principal part distinguishes removable singularities poles and essential singularities.

## Exact Preconditions
An isolated singularity and a valid annulus are identified.

## Procedure
Expand in the correct annulus then inspect negative powers.

## Branch Conditions
Branch by different annuli around other singularities.

## Failure Modes
One algebraic expression can have different Laurent series on different annuli.

## Counterexample Patterns
Test convergence radius against nearest singularities.

## Verification Recipe
Multiply by the expected pole power or bound the function for removability.

## Mini Example
e^z/z^2 has a pole of order two at zero.

## Alternative Strategy
Use limit tests or residues.

## Stop / Escalate Conditions
Escalate when the singularity is not isolated.
