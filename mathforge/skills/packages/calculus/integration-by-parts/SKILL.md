---
name: integration-by-parts
version: 3.0
domain: calculus
subdomain: integration
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: integration by parts, product derivative
problem_patterns: integral product, logarithm integral
method_family: integration-by-parts
alternative_skills: rational-substitution
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Recognition
Use when the problem exposes integral product, logarithm integral.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
Integration by parts is the integrated product rule including boundary terms.

## Exact Preconditions
Chosen factors are differentiable and integrable on the domain.

## Procedure
Choose u and dv then compute uv minus integral v du.

## Branch Conditions
Branch for definite versus improper integrals.

## Failure Modes
Boundary terms at improper endpoints cannot be assumed zero.

## Counterexample Patterns
Test every improper boundary by a limit.

## Verification Recipe
Differentiate the antiderivative or reconstruct the product rule.

## Mini Example
Integral x e^x dx=e^x(x-1)+C.

## Alternative Strategy
Use substitution or parameter differentiation.

## Stop / Escalate Conditions
Escalate when boundary limits diverge.
