---
name: dominated-convergence
version: 3.0
domain: calculus
subdomain: integration
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: dominated convergence, exchange limit integral
problem_patterns: limit under integral, measurable functions
method_family: dominated-convergence
alternative_skills: uniform-convergence
description: Exchange a limit and an integral only after almost everywhere convergence and one integrable dominator are proved.
negative_triggers: pointwise convergence only, nonintegrable bound, finite sample evidence
required_observables: almost everywhere convergence, measurable functions, integrable dominator
requires: numerical_residual
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: numerical_residual
---
## Recognition
Use when a sequence of measurable functions is integrated and the target asks to interchange a limit and an integral. The phrase “bounded” alone is not enough.

## Do Not Use When
Do not apply from vocabulary overlap, pointwise convergence alone, a dominator that depends on the index, or a bound that is not integrable on the whole measure space.

## Core Theorem
On a measure space, if measurable f_n converge to f almost everywhere, |f_n| is bounded by one integrable g for every n, and g is in L^1, then the integrals of f_n converge to the integral of f. The three hypotheses are independent obligations.

## Exact Preconditions
Name the measure space and its domain; prove measurability, f_n→f almost everywhere, |f_n(x)|≤g(x) for all n outside one null set, and ∫|g|<∞. A finite measure space does not replace the integrable-dominator proof unless a uniform bound is supplied.

## Procedure
1. State the quantifiers and identify a single candidate limit f.
2. Prove almost-everywhere convergence, including the exceptional set.
3. Exhibit an index-independent measurable g and prove |f_n|≤g.
4. Establish g∈L^1 on the complete domain, then invoke dominated convergence.
5. Record which obligation each estimate closes before writing the integral equality.

## Branch Conditions
For a finite measure space, a uniform constant bound may yield an integrable dominator; for an infinite space it generally does not. Treat parameter-dependent domains, complex-valued functions, and subsequences separately and preserve the almost-everywhere qualifier.

## Failure Modes
Pointwise boundedness, convergence at sampled points, local domination, or an index-dependent g does not establish the theorem. A divergent or merely conditionally integrable bound leaves the interchange obligation open.

## Counterexample Patterns
Try mass escaping to infinity, a moving spike whose height grows while its support shrinks, or f_n(x)=n·1_(0,1/n)(x). These expose why pointwise convergence and finite numerical checks are insufficient.

## Verification Recipe
Use `numerical_residual` only as finite-sample support for an algebraic subexpression; it cannot verify almost-everywhere convergence, integrability, or a universal interchange. The Verifier must explicitly review all three theorem obligations and mark the claim incomplete when any one is missing.

## Mini Example
On [0,1] with Lebesgue measure, x^n→0 almost everywhere and |x^n|≤1 with 1∈L^1, so the theorem justifies passing the limit through the integral.

## Alternative Strategy
If 0≤f_n and f_n increases, test monotone convergence; if a uniform bound on the integral error is available, use uniform convergence. These alternatives require their own hypotheses.

## Stop / Escalate Conditions
Escalate when the exceptional set, global integrability, or an index-independent dominator cannot be proved. Never close the obligation from numerical samples alone.

