---
name: proof-strategy-selection
version: 3.0
domain: logic
subdomain: proof_planning
kind: method
roles: PrimarySolver,AlternativeSolver,LemmaCurator,VerifierSkeptic,RepairAgent
triggers: choose proof method, proof plan, prove theorem, select strategy
problem_patterns: quantified theorem, implication, equivalence, existence or uniqueness claim
method_family: proof-method-selection
alternative_skills: mathematical-induction,contradiction-contrapositive,case-split-wlog,existence-uniqueness
description: Select a proof architecture from the statement shape and maintain explicit obligations through the selected branches.
negative_triggers: computation-only question, missing proposition, request to choose by keyword alone
required_observables: quantifier shape, hypotheses, target connective, candidate obligations
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Recognition
Use before proof synthesis when the theorem shape suggests direct proof, contrapositive, contradiction, cases, induction, existence, uniqueness, or a counterexample.

## Do Not Use When
Do not select a method from a surface word, do not turn a numerical check into a theorem, and do not use a contradiction branch without writing the negation of the exact target.

## Core Theorem
Proof methods are sound transformations of obligations: an implication may be proved directly or by contrapositive, an equivalence requires both directions, a universal claim can be refuted by one admissible counterexample, and induction requires a valid base and quantified step.

## Exact Preconditions
Normalize the proposition with variable domains, quantifier order, hypotheses, and conclusion. Identify whether the target is implication, equivalence, universal, existential, uniqueness, or a finite disjunction. Every selected method must map to a finite list of named obligations.

## Procedure
1. Parse the logical outermost connective and list all assumptions.
2. Choose the least-assumptive method that matches the dependency direction.
3. Publish an obligation graph with base, bridge, witness, or contradiction nodes as appropriate.
4. Ask an alternative branch to challenge the choice when the first method has a missing condition or circular dependency.
5. Close obligations only after a claim-specific mathematical verification; retain the selected strategy/version in the candidate lineage.

## Branch Conditions
Direct proof is preferred when hypotheses rewrite the target. Use contrapositive when the negated conclusion exposes a usable hypothesis. Use contradiction when the negation yields a finite inconsistency. Use cases when an exhaustive partition is available. Use induction only for a well-founded indexed family.

## Failure Modes
Proving a converse instead of the implication, losing a quantifier, assuming the desired result, using a non-exhaustive case split, or treating a witness for one instance as a universal construction.

## Counterexample Patterns
Try a false converse, an empty domain, an existential statement with a nonconstructive witness, and a case split that omits zero or a boundary. If one example falsifies a universal statement, record it as a counterexample rather than forcing a proof.

## Verification Recipe
Mathematical verification checks each obligation and dependency. Host verification uses `symbolic_equivalence` only for domain-bounded normalization of formulas; its result is conditional on stated assumptions and does not certify the proof. Record the proposition, assumptions, and comparison domain.

## Mini Example
For “if n^2 is even then n is even,” the conclusion’s negation makes contrapositive useful. The plan still needs the integer-domain assumption and the factorization of an odd square.

## Alternative Strategy
Switch to a claim-local lemma, a finite counterexample search, or a case split when the selected branch has an open obligation. Never keep two strategies as if both were completed proofs.

## Stop / Escalate Conditions
Escalate on ambiguous quantifiers, circular dependencies, an unproved exhaustiveness claim, or a branch whose assumptions differ from the original theorem. A plan is not a final answer.
