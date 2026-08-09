---
name: conditional-expectation
version: 3.0
domain: probability
subdomain: expectation
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: conditional expectation, tower property, law total expectation
problem_patterns: nested expectation, latent variable
method_family: conditional-expectation
alternative_skills: indicator-linearity
requires: density_normalization
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: density_normalization
---
## Recognition
Use when the problem exposes nested expectation, latent variable.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
The tower property averages a conditional expectation over the conditioning sigma-field.

## Exact Preconditions
Integrability and the nesting of sigma-fields are established.

## Procedure
Condition on a variable that simplifies the quantity then average.

## Branch Conditions
Branch for discrete sums and continuous integrals.

## Failure Modes
Conditioning on incomparable sigma-fields does not permit tower simplification.

## Counterexample Patterns
Test with a small joint table.

## Verification Recipe
Compare against direct expectation.

## Mini Example
E[X]=E[E[X|Y]].

## Alternative Strategy
Use indicators or total probability.

## Stop / Escalate Conditions
Escalate if the conditional law is undefined or integrability fails.
