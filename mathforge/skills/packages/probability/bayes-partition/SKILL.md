---
name: bayes-partition
version: 3.0
domain: probability
subdomain: probability
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: bayes, posterior, prior
problem_patterns: posterior probability, diagnostic
method_family: bayes-partition
alternative_skills: conditional-probability
requires: density_normalization
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: density_normalization
---
## Recognition
Use when the problem exposes posterior probability, diagnostic.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
Bayes theorem reverses conditioning using a complete positive-probability partition.

## Exact Preconditions
Priors likelihoods and evidence normalization are specified.

## Procedure
Compute each joint weight then divide by their total.

## Branch Conditions
Branch over all latent hypotheses.

## Failure Modes
Ignoring a hypothesis from the evidence denominator inflates the posterior.

## Counterexample Patterns
Test posterior probabilities sum to one.

## Verification Recipe
Reconstruct evidence probability by total probability.

## Mini Example
Posterior is prior times likelihood normalized across hypotheses.

## Alternative Strategy
Use odds form or direct joint tables.

## Stop / Escalate Conditions
Escalate if priors or likelihoods are missing.
