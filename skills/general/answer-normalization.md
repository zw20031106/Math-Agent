---
name: answer-normalization
subject: general-math
kind: general
version: 2.0
triggers: final answer, exact value, requested output, 答案, 精确值
roles: PrimarySolver, AlternativeSolver, RepairAgent, LLMFinalizer
---
## Triggers

Use for every candidate and final answer, especially fractions, radicals,
vectors, matrices, sets, intervals, polynomials, and algebraic structures.

## Roles

Solvers produce the exact answer; Repair preserves or corrects it; Finalizer
must reproduce it without semantic change.

## Method decision tree

Identify the requested output object, keep an exact symbolic form when
available, and only add a decimal as a labeled approximation.

## Theorem preconditions

Preserve domains, endpoint inclusion, ordering conventions, basis choice, and
normalization conventions that determine the answer's meaning.

## Common errors

Do not return an input object's type, drop tuple order, lose set braces, round
an exact value, or replace a proof conclusion with `QED` alone.

## Counterexample checklist

Check sign, endpoint closure, component order, matrix shape, repeated roots,
units, and equivalent but differently normalized forms.

## Compatible check types

Use `answer_type_check`, `symbolic_equivalence`, or `reasoning`; these are Host
suggestions, not model tool calls.

## Answer normalization

Place one unambiguous exact value in `final_answer` and repeat it in the public
conclusion without changing notation-dependent meaning.

## Trace step guidance

The last public step must state the requested object and the exact final answer.
