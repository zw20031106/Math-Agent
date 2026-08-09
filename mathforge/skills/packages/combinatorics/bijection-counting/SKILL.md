---
name: bijection-counting
version: 3.0
domain: combinatorics
subdomain: counting
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: bijection, one-to-one correspondence
problem_patterns: count finite structures, encode objects
method_family: bijection-counting
alternative_skills: double-counting
requires: small_case_enumeration
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: small_case_enumeration
---
## Recognition
Use when the problem exposes count finite structures, encode objects.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
A bijection preserves cardinality by a reversible mapping.

## Exact Preconditions
Both object classes and inverse map are fully specified.

## Procedure
Define forward and inverse maps then prove mutual identity.

## Branch Conditions
Branch if symmetries make encodings nonunique.

## Failure Modes
An injection alone gives only an inequality.

## Counterexample Patterns
Test collisions and objects missing from the image.

## Verification Recipe
Apply both compositions on arbitrary objects.

## Mini Example
Binary strings with k ones biject to k-subsets.

## Alternative Strategy
Use recurrence or generating functions.

## Stop / Escalate Conditions
Escalate when canonical representatives are unavailable.
