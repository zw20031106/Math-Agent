---
name: branch-cut-integral
version: 3.0
domain: complex_analysis
subdomain: integration
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: branch cut, keyhole contour, log branch
problem_patterns: multivalued complex function, contour integral
method_family: branch-cut-integral
alternative_skills: residue-theorem
description: Evaluate a contour integral involving a multivalued function after fixing one analytic branch and its jump across the cut.
negative_triggers: unspecified branch, contour crosses cut, nonintegrable endpoint
required_observables: branch domain, argument convention, contour orientation
requires: numerical_residual
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: numerical_residual
---
## Recognition
Use when powers, logarithms, roots, or inverse functions are multivalued and a keyhole, slit, or dog-bone contour is proposed.

## Do Not Use When
Do not choose this if the branch, argument range, contour orientation, or endpoint behavior is unspecified. A numerical contour value cannot repair an inconsistent branch choice.

## Core Theorem
After deleting a cut and fixing a continuous argument interval, z^α and Log z are single-valued analytic on the branch domain. The two banks of a cut differ by the prescribed monodromy factor, and a contour integral is the oriented sum of all pieces.

## Exact Preconditions
State the branch function, cut, argument interval, contour and orientation. Prove analyticity on and between contour pieces, account for endpoint indentations, and establish convergence/vanishing of every auxiliary arc before taking a limit.

## Procedure
1. Fix the branch and write its values on both banks of the cut.
2. Parameterize each segment with its orientation and list the induced jump factor.
3. Bound small and large circular arcs and justify their limiting contribution.
4. Combine the real-axis or bank integrals only after checking endpoint integrability.
5. Cross-check the final orientation and branch factor with a simple integer exponent.

## Branch Conditions
Separate upper and lower bank arguments, inner versus outer radius limits, and integer versus noninteger exponents. A different argument convention changes the jump and must be carried through every segment.

## Failure Modes
Using principal values on one bank and another branch on the other, reversing an orientation, omitting an arc, or assuming an endpoint is integrable invalidates the result. Branch points are not ordinary poles.

## Counterexample Patterns
Test an integer exponent where the jump should vanish, reverse the contour orientation, and inspect a parameter for which the endpoint exponent is ≤−1.

## Verification Recipe
Use `numerical_residual` only as finite-sample support for a parameterized segment after the branch is fixed. It cannot certify analyticity, orientation, jump factors, or vanishing arcs; the proof trace must close those contour obligations explicitly.

## Mini Example
For a keyhole contour with a fixed branch of z^α, the two banks differ by e^{2πiα}; when α is an integer the factor is one and no branch jump remains.

## Alternative Strategy
Use a real substitution or residues when the integrand is single-valued on a simpler contour; verify that no hidden branch point remains.

## Stop / Escalate Conditions
Escalate when the branch domain or endpoint integrability is unresolved, an arc does not vanish, or the contour intersects the cut. Do not report a numerical value as a proof.

