---
name: proof-theory
version: 3.0
domain: logic
subdomain: foundations
kind: method
roles: PrimarySolver,AlternativeSolver,LemmaCurator,VerifierSkeptic,RepairAgent
triggers: proof theory, soundness, completeness, proof dependency, structural induction
problem_patterns: formal derivation, inference system, proof tree, normalization or dependency audit
method_family: proof-dependency-and-meta-theory
alternative_skills: proof-obligation,mathematical-induction
description: Make inference rules, proof dependencies, and meta-theoretic obligations explicit without claiming a formal kernel check.
negative_triggers: informal plausibility only, unspecified calculus, rule application with missing premises
required_observables: formal system, rule signatures, proof tree, dependency graph, soundness target
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Recognition
Use when a solution depends on a chain of lemmas, an inference system, structural induction, soundness/completeness, or checking whether every proof step has licensed premises.

## Do Not Use When
Do not call a readable derivation sound without a rule and premise audit, do not conflate semantic truth with derivability, and do not claim completeness for an unspecified calculus.

## Core Theorem
A derivation is a finite tree whose every node follows an allowed rule from its premises. Soundness states derivability implies semantic validity; completeness is the converse and requires a specified logic and semantics. Structural induction follows the constructors of the proof/object syntax.

## Exact Preconditions
Name the language, axioms/rules, contexts, semantics, and target relation. Record each node’s rule, premises, discharged assumptions, and dependencies. Separate an object-level theorem from a meta-theorem about the calculus.

## Procedure
1. Freeze the formal statement and calculus version.
2. Build a proof-dependency DAG/tree and label every inference.
3. Check premises, variable freshness, substitutions, and discharged assumptions locally.
4. For a soundness/structural argument, prove the induction invariant for every rule/constructor.
5. Report unverified semantic or completeness obligations instead of inferring them from a successful parse.

## Branch Conditions
Use a local derivation audit for ordinary proofs, structural induction for syntax-defined objects, and separate semantic induction for soundness. Cut/elimination or normalization claims require their own termination and measure obligations.

## Failure Modes
Circular lemma dependencies, an illicit weakening/substitution, a missing eigenvariable condition, a proof tree with an open leaf, or a semantic argument silently assuming completeness.

## Counterexample Patterns
Test an empty context, a rule with an unbound variable, a proof that uses its conclusion as a premise, and a nonterminating rewrite sequence. A syntactically well-formed tree can still be invalid.

## Verification Recipe
Mathematical verification is the rule/premise and semantic argument. Host verification uses `symbolic_equivalence` only for conditional formula normalization with the stated domain; it does not implement a proof kernel, soundness, or completeness checker, so the result is supporting evidence and open obligations remain explicit.

## Mini Example
For modus ponens, record premises A→B and A, then derive B. A proof tree containing only B or a parser success has not closed the obligation.

## Alternative Strategy
Reduce the theorem to claim-local obligations and use the ordinary proof Skills. Use a formal proof assistant only when a separately configured Lean capability exists.

## Stop / Escalate Conditions
Escalate on an unspecified calculus, circular dependency, open leaf, or any request to certify soundness/completeness without a formal checker and semantic model.
