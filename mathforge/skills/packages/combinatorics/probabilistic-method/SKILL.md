---
name: probabilistic-method
version: 3.0
domain: combinatorics
subdomain: proof
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: probabilistic method, expectation existence, random construction
problem_patterns: prove existence, random object
method_family: probabilistic-method
alternative_skills: pigeonhole-extremal
requires: small_case_enumeration
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: small_case_enumeration
---
## Recognition
Use when the problem exposes prove existence, random object.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
If a nonnegative badness variable has expectation below one then an outcome with zero badness exists.

## Exact Preconditions
The probability space covers valid objects and expectation is correctly bounded.

## Procedure
Choose a random object define bad events and bound expected violations.

## Branch Conditions
Branch between union bound and alteration.

## Failure Modes
Positive probability must refer to an admissible object.

## Counterexample Patterns
Test dependencies and support restrictions.

## Verification Recipe
Compute a finite-space example or verify every expectation term.

## Mini Example
A random coloring with expected monochromatic edges below one yields a proper instance.

## Alternative Strategy
Use explicit greedy construction.

## Stop / Escalate Conditions
Escalate when the expectation bound does not cross the existence threshold.
