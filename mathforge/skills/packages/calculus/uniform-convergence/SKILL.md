---
name: uniform-convergence
version: 3.0
domain: calculus
subdomain: analysis
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: uniform convergence, sup norm
problem_patterns: sequence of functions, interchange continuity
method_family: uniform-convergence
alternative_skills: dominated-convergence
description: Prove one index threshold works for every point by controlling the supremum norm on the stated domain.
negative_triggers: pointwise convergence only, sampled point agreement, unbounded domain without a global bound
required_observables: common domain, supremum error, epsilon threshold
requires: numerical_residual
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: numerical_residual
---
## Recognition
Use when the target quantifies over every x in a common domain, asks for a sup norm, or transfers continuity/integration properties through a function sequence.

## Do Not Use When
Do not infer uniform convergence from pointwise convergence, agreement on a finite grid, or a small numerical residual. First state the domain and the order of quantifiers.

## Core Theorem
f_n→f uniformly on E means for every ε>0 there is one N such that n≥N implies |f_n(x)-f(x)|<ε for every x∈E. Consequences such as continuity preservation need their own hypotheses (for example continuity of each f_n).

## Exact Preconditions
Fix E, f, and the codomain; prove a bound sup_{x∈E}|f_n-f|→0 or an equivalent ε–N statement. For a property-transfer claim, separately verify the property for the approximants and any completeness/integrability hypotheses.

## Procedure
1. Write the uniform ε–N quantifiers before estimating.
2. Compute or upper-bound the supremum over the entire domain, not a sample.
3. Choose N from ε only, then verify the bound for every x∈E.
4. Apply the requested continuity/integral/derivative theorem only after its side conditions are checked.

## Branch Conditions
Separate compact from noncompact domains, closed from punctured domains, and scalar from norm-valued functions. A bound that is uniform on every compact subset is only local uniform convergence unless a global argument is supplied.

## Failure Modes
An N depending on x, a supremum taken over a truncated interval, or a moving peak at infinity proves at most pointwise or compact convergence. Uniform convergence alone does not justify termwise differentiation.

## Counterexample Patterns
Use f_n(x)=x^n on [0,1] or a moving triangular spike to distinguish pointwise from uniform convergence. Check the endpoint and the tail of an unbounded domain.

## Verification Recipe
Compute an analytic supremum bound when possible. `numerical_residual` over finite samples is only supporting evidence and cannot close the universal sup-norm obligation; report the domain and a proof of the global bound.

## Mini Example
For f_n(x)=x/n on [0,1], sup|f_n|=1/n→0, so convergence to zero is uniform.

## Alternative Strategy
Use a direct ε–N proof, a monotone convergence theorem for suprema, or a known uniform convergence criterion. Do not replace the proof with a finite grid.

## Stop / Escalate Conditions
Escalate when the supremum is infinite, the domain is unspecified, or only pointwise estimates are available. Keep property-transfer claims open until their separate hypotheses are verified.

