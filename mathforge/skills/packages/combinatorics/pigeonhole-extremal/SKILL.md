---
name: pigeonhole-extremal
version: 3.0
domain: combinatorics
subdomain: proof
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: pigeonhole, extremal, maximal
problem_patterns: existence by counting, extremal object
method_family: pigeonhole-extremal
alternative_skills: double-counting
requires: small_case_enumeration
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: small_case_enumeration
---
## Recognition
Use when the problem exposes existence by counting, extremal object.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
More objects than capacity forces an overloaded box; extremal choice adds a monotone comparison.

## Exact Preconditions
Boxes and capacity bounds exhaust all objects.

## Procedure
Define the partition or select an extremal object then derive the forced relation.

## Branch Conditions
Branch for weighted capacities.

## Failure Modes
Overlapping boxes invalidate a simple capacity sum.

## Counterexample Patterns
Test equality at total capacity.

## Verification Recipe
Construct the allocation bound explicitly.

## Mini Example
Among n+1 integers two share a residue mod n.

## Alternative Strategy
Use double counting or probabilistic method.

## Stop / Escalate Conditions
Escalate if membership is not a partition.
