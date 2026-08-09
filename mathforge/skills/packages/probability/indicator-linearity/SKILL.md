---
name: indicator-linearity
version: 3.0
domain: probability
subdomain: expectation
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: indicator, linearity of expectation
problem_patterns: expected count, dependent events
method_family: indicator-linearity
alternative_skills: conditional-expectation
requires: small_case_enumeration
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: small_case_enumeration
---
## Recognition
Use when the problem exposes expected count, dependent events.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
An expected count equals the sum of event probabilities without requiring independence.

## Exact Preconditions
The count is represented exactly as a finite or integrable sum of indicators.

## Procedure
Define one indicator per counted feature then sum expectations.

## Branch Conditions
Branch for infinite sums where interchange needs justification.

## Failure Modes
Independence is unnecessary but double counting features changes the variable.

## Counterexample Patterns
Test a dependent example.

## Verification Recipe
Enumerate small outcomes and compare average count.

## Mini Example
Expected fixed points of a random permutation equal one.

## Alternative Strategy
Use conditional expectation or generating functions.

## Stop / Escalate Conditions
Escalate for infinite sums without Tonelli or domination.
