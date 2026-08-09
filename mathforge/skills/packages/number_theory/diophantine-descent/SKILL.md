---
name: diophantine-descent
version: 3.0
domain: number_theory
subdomain: number theory
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: descent, minimal counterexample, diophantine
problem_patterns: integer equation, infinite descent
method_family: diophantine-descent
alternative_skills: modular-congruence
requires: small_case_enumeration
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: small_case_enumeration
---
## Recognition
Use when the problem exposes integer equation, infinite descent.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
Infinite descent refutes a positive-integer solution by constructing a strictly smaller solution of the same type.

## Exact Preconditions
A well-founded positive measure and preservation of all constraints are proven.

## Procedure
Assume a minimal solution then construct a smaller admissible one.

## Branch Conditions
Branch on gcd normalization and parity.

## Failure Modes
A smaller tuple that violates primitiveness does not complete descent.

## Counterexample Patterns
Test the construction at boundary values.

## Verification Recipe
Verify integrality positivity equation preservation and strict decrease.

## Mini Example
The classic sqrt(2) proof descends common factors after parity.

## Alternative Strategy
Use modular obstruction or factorization.

## Stop / Escalate Conditions
Escalate if the decrease measure is not strict.
