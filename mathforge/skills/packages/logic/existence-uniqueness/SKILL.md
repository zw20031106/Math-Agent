---
name: existence-uniqueness
version: 3.0
domain: logic
subdomain: proof
kind: method
roles: PrimarySolver,AlternativeSolver,LemmaCurator,VerifierSkeptic,RepairAgent
triggers: exists unique, existence, uniqueness, exactly one, construct a solution
problem_patterns: witness construction, solution set, equation with uniqueness claim
method_family: existence-and-uniqueness
alternative_skills: proof-strategy-selection,contradiction-contrapositive
description: Separate witness construction from the proof that any two admissible witnesses coincide.
negative_triggers: numerical candidate only, witness outside the domain, uniqueness inferred from monotonic samples
required_observables: admissible domain, witness, existence obligations, pairwise uniqueness obligations
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Recognition
Use for “there exists,” “there is exactly one,” or a problem that asks for a constructed object and a uniqueness proof under stated constraints.

## Do Not Use When
Do not treat a numerical approximation as a witness for an exact statement, do not prove uniqueness without proving existence, and do not compare candidates outside the admissible domain.

## Core Theorem
∃x P(x) requires one x in the domain with P(x). ∃!x P(x) additionally requires that for all y,z in the domain, P(y) and P(z) imply y=z. The two obligations are logically independent.

## Exact Preconditions
State the domain, parameters, regularity assumptions, and the exact predicate P. For uniqueness identify the relation or monotonicity/injectivity lemma that can compare arbitrary witnesses; do not use only the constructed witness.

## Procedure
1. Search for an explicit witness or a theorem supplying one; verify every side condition.
2. Publish the existence derivation with no uniqueness assumptions.
3. Let y and z be arbitrary admissible witnesses and derive equality through injectivity, monotonicity, algebra, or a contradiction.
4. Check boundary, degenerate, and parameter cases separately.
5. State whether the result is existence, uniqueness, or both, and retain unresolved parts as open obligations.

## Branch Conditions
Use monotonicity for scalar equations, contraction/fixed-point arguments when their hypotheses hold, compactness for abstract existence, and direct comparison for algebraic uniqueness. A theorem with several parameter regimes needs one witness/uniqueness branch per regime.

## Failure Modes
An invalid witness, circular substitution of the desired value, a local derivative test presented as global uniqueness, or an unhandled parameter where the domain is empty or the function is constant.

## Counterexample Patterns
Test an empty domain, a flat function with many roots, a boundary-only witness, and a parameter value where the derivative vanishes. A small residual cannot distinguish multiple nearby roots.

## Verification Recipe
Mathematical verification checks witness admissibility and the arbitrary-pair uniqueness argument. Host verification uses `symbolic_equivalence` for conditional algebraic comparison under declared domains; it is not an existence or uniqueness proof and must be labeled supporting algebra.

## Mini Example
For x^2=1 over the reals, witnesses 1 and -1 prove existence but disprove uniqueness. Over x≥0, the witness 1 plus the domain-restricted comparison yields uniqueness.

## Alternative Strategy
Use a counterexample to reject a uniqueness claim, or use a set-valued solution description when the task asks only for all solutions.

## Stop / Escalate Conditions
Escalate when no admissible witness is available, the comparison lemma is local only, the domain changes between branches, or a parameter case is unresolved.
