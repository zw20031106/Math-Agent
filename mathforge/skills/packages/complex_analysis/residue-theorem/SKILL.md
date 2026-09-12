---
name: residue-theorem
version: 3.0
domain: complex_analysis
subdomain: integration
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: residue, contour integral, pole
problem_patterns: complex contour integral, meromorphic
method_family: residue-theorem
alternative_skills: laurent-classification
description: Reduce a contour integral to residues after proving meromorphicity, orientation, and exclusion of singularities from the contour.
negative_triggers: branch point, singularity on contour, unspecified orientation
required_observables: meromorphic neighborhood, contour orientation, enclosed singularities
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Recognition
Use for a positively or negatively oriented closed contour enclosing isolated poles of a meromorphic integrand and no singularity on the path.

## Do Not Use When
Do not apply to branch points, essential nonisolated singular sets, or a pole on the contour without a separately justified principal-value theorem. Orientation must not be inferred.

## Core Theorem
For a piecewise smooth closed contour Γ avoiding all singularities and with winding number n(Γ,a), ∮Γ f(z)dz=2πi Σ n(Γ,a)Res(f,a) over enclosed isolated singularities.

## Exact Preconditions
Prove f is meromorphic on a neighborhood of Γ and its interior, list all singularities and their orders, verify none lies on Γ, and state the contour orientation/winding numbers. Use the residue definition valid for each pole order.

## Procedure
1. Locate and classify every singularity relative to Γ.
2. Compute each residue using a justified local expansion or derivative formula.
3. Multiply by orientation/winding numbers and sum exactly.
4. Check the result on a simple parameterized contour and inspect any branch assumption.

## Branch Conditions
Separate simple, higher-order, and essential isolated singularities; reverse the sign for negative orientation; handle parameter-dependent pole inclusion as separate cases.

## Failure Modes
Including an outside pole, omitting multiplicity, reversing orientation, or treating a branch point as a pole changes the integral. A symbolic expression that ignores the contour is incomplete.

## Counterexample Patterns
Move a pole onto Γ, reverse orientation, and compare a pole of order two with the simple-pole formula.

## Verification Recipe
Use `symbolic_equivalence` only to check local algebra or residue expressions under explicit domains. It cannot establish meromorphicity, contour exclusions, or winding numbers; the proof trace must state those conditions before the final sum.

## Mini Example
The positively oriented unit circle around f(z)=1/z has one enclosed simple pole with residue 1, so the integral is 2πi.

## Alternative Strategy
Use Cauchy's integral formula or a real-variable substitution when the contour and singularity structure make those hypotheses clearer.

## Stop / Escalate Conditions
Escalate for branch points, boundary singularities, unspecified winding numbers, or unresolved residue classification. Do not report a formal residue sum as complete.

