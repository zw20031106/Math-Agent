---
name: conditional-probability
version: 3.0
domain: probability
subdomain: probability
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: conditional probability, given event
problem_patterns: probability given condition, event intersection
method_family: conditional-probability
alternative_skills: bayes-partition
requires: density_normalization
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: density_normalization
---
## Recognition
Use when the problem exposes probability given condition, event intersection.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
P(A|B)=P(A intersection B)/P(B) when P(B)>0.

## Exact Preconditions
The conditioning event has positive probability.

## Procedure
Restrict to B then normalize intersection mass.

## Branch Conditions
Branch for discrete densities and sigma-field conditioning.

## Failure Modes
Conditioning on a null event needs a different framework.

## Counterexample Patterns
Test B with zero or tiny probability.

## Verification Recipe
Check the conditional probabilities over a partition sum to one.

## Mini Example
For a fair die P(even|greater than 3)=2/3.

## Alternative Strategy
Use Bayes theorem or direct enumeration.

## Stop / Escalate Conditions
Escalate for conditioning on measure-zero continuous events.
