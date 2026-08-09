---
name: inclusion-exclusion
version: 3.0
domain: combinatorics
subdomain: counting
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: inclusion exclusion, overlap, forbidden
problem_patterns: union count, avoid properties
method_family: inclusion-exclusion
alternative_skills: mobius-inversion
requires: small_case_enumeration
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: small_case_enumeration
---
## Recognition
Use when the problem exposes union count, avoid properties.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
The union size is the alternating sum of intersection sizes.

## Exact Preconditions
The finite family of properties and intersection counts are defined.

## Procedure
Choose bad-event sets then sum intersections by subset size.

## Branch Conditions
Branch when symmetry collapses intersection types.

## Failure Modes
Stopping after pairwise terms is generally incomplete.

## Counterexample Patterns
Test three sets with a triple overlap.

## Verification Recipe
Enumerate small cases and compare the alternating sum.

## Mini Example
|A union B|=|A|+|B|-|A intersection B|.

## Alternative Strategy
Use complementary counting or Mobius inversion.

## Stop / Escalate Conditions
Escalate when high-order intersections cannot be characterized.
