---
name: mobius-inversion
version: 3.0
domain: number_theory
subdomain: number theory
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: mobius inversion, divisor sum, multiplicative
problem_patterns: invert divisor sum, arithmetic function
method_family: mobius-inversion
alternative_skills: inclusion-exclusion
requires: small_case_enumeration
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: small_case_enumeration
---
## Recognition
Use when the problem exposes invert divisor sum, arithmetic function.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
If g(n)=sum_{d|n} f(d), then f(n)=sum_{d|n} mu(d)g(n/d).

## Exact Preconditions
Functions are defined on positive integers and the divisor relation matches the formula.

## Procedure
Identify the convolution with the constant-one function then convolve with mu.

## Branch Conditions
Branch for poset versus classical divisor inversion.

## Failure Modes
Changing d to n/d inconsistently corrupts the inversion.

## Counterexample Patterns
Test prime powers and n=1.

## Verification Recipe
Recompute the original divisor sum from the recovered function.

## Mini Example
If g(n)=number of divisors weighted by f=1, inversion recovers 1.

## Alternative Strategy
Use generating functions or inclusion-exclusion.

## Stop / Escalate Conditions
Escalate when the summation order is not divisor inclusion.
