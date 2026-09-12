---
name: rouche-zero-count
version: 3.0
domain: complex_analysis
subdomain: proof
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: rouche, zeros inside contour, dominates
problem_patterns: count complex zeros, contour dominance
method_family: rouche-zero-count
alternative_skills: argument-principle
description: Transfer a zero count using strict boundary dominance between two holomorphic functions on a specified contour.
negative_triggers: non-strict dominance, boundary singularity, function not holomorphic inside
required_observables: holomorphic neighborhood, strict boundary margin, dominant zero count
requires: numerical_residual
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: numerical_residual
---
## Recognition
Use when a polynomial or holomorphic function splits as f+g and one term has an easy zero count while |g|<|f| is plausible on a simple closed contour.

## Do Not Use When
Do not use a non-strict inequality, a contour containing a singularity, or a function that is only meromorphic inside. “Dominates at sampled points” is not global boundary dominance.

## Core Theorem
If f and g are holomorphic on and inside Γ and |g(z)|<|f(z)| for every z∈Γ, then f and f+g have the same number of zeros inside Γ, counted with multiplicity. Strictness and the full contour are essential.

## Exact Preconditions
Specify Γ and orientation, prove holomorphicity on a neighborhood of its closure, establish f(z)≠0 on Γ, and prove a strict margin |f|−|g|>0 at every boundary point. Count zeros of the dominant f in the same interior.

## Procedure
1. Choose f with an elementary interior zero count and set g=(f+g)−f.
2. Parameterize Γ and derive an analytic lower bound for |f|−|g|.
3. Prove the bound is strictly positive globally, including corners or endpoints.
4. Apply Rouché and transfer the multiplicity-aware count.
5. Recheck the margin if the contour radius or parameters change.

## Branch Conditions
Handle circles, piecewise smooth contours, and parameter-dependent radii separately. If equality occurs at any boundary point, switch to another estimate or another theorem.

## Failure Modes
A ≥ inequality, a zero of f on Γ, or a missing holomorphic neighborhood leaves Rouché unavailable. Counting only distinct roots loses multiplicities.

## Counterexample Patterns
Search for equality points on Γ, perturb a coefficient until a root crosses the boundary, and compare with a direct factorization for a low-degree case.

## Verification Recipe
Use `numerical_residual` only as finite-sample support for a proposed boundary margin. It cannot certify strict dominance on the entire contour or holomorphicity; the Verifier must provide a global inequality and mark the obligation open otherwise.

## Mini Example
On |z|=2, f=z^3 and g=z+1 satisfy |f|=8 and |g|≤3, so the strict margin transfers the three-zero count.

## Alternative Strategy
Use the argument principle or direct factorization when no global strict margin can be proved.

## Stop / Escalate Conditions
Escalate when the margin is only sampled, equality is possible, or an interior singularity is present. Do not convert numerical agreement into a Rouché pass.

