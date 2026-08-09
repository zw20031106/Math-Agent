---
name: order-statistics
version: 3.0
domain: probability
subdomain: probability
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: order statistic, maximum distribution, minimum distribution
problem_patterns: distribution of maximum, kth sample
method_family: order-statistics
alternative_skills: conditional-probability
requires: density_normalization
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: density_normalization
---
## Recognition
Use when the problem exposes distribution of maximum, kth sample.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
For iid samples the maximum CDF is F(x)^n and kth order densities use binomial ranks under regularity.

## Exact Preconditions
Samples are iid and continuity assumptions for density formulas are stated.

## Procedure
Express the event using counts below x then differentiate only if justified.

## Branch Conditions
Branch for discrete distributions and ties.

## Failure Modes
Continuous density formulas fail with atoms.

## Counterexample Patterns
Test n=1 and distributions with ties.

## Verification Recipe
Check the resulting CDF endpoints and density normalization.

## Mini Example
For iid Uniform(0,1), max CDF is x^n.

## Alternative Strategy
Use symmetry or direct enumeration.

## Stop / Escalate Conditions
Escalate when samples are dependent.
