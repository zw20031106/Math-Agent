---
name: derivative-stationarity
version: 3.0
domain: calculus
subdomain: optimization
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: derivative, stationary, critical point
problem_patterns: optimize differentiable function, extrema
method_family: derivative-stationarity
alternative_skills: monotonicity-partition
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Recognition
Use when the problem exposes optimize differentiable function, extrema.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
Interior differentiable local extrema have zero derivative; endpoints and singular points remain candidates.

## Exact Preconditions
The domain and differentiability intervals are explicit.

## Procedure
Find critical and nondifferentiable points then compare with boundaries.

## Branch Conditions
Branch for open domains and unbounded objectives.

## Failure Modes
Stationary points need not be extrema.

## Counterexample Patterns
Test inflectionary stationary points and endpoints.

## Verification Recipe
Evaluate the objective and derivative sign around each candidate.

## Mini Example
For f=x^2 on R, f'=2x gives minimum x=0.

## Alternative Strategy
Use convexity or completing the square.

## Stop / Escalate Conditions
Escalate for nonsmooth objectives requiring subgradients.
