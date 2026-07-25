---
name: stochastic-processes
subject: stochastic-processes
kind: domain
version: 2.0
triggers: Brownian, Markov chain, Poisson process, stopping time, stationary distribution, 随机过程, 平稳分布
roles: PrimarySolver, AlternativeSolver, VerifierSkeptic, RepairAgent
---
## Triggers

Brownian motion, stopping/exit times, Poisson processes, conditional counting,
Markov chains, transition matrices, and stationary laws.

## Roles

Solvers use conditioning, generators, or transition structure; Verifier checks
filtration/state assumptions and normalization; Repair corrects failed local
probability Claims.

## Method decision tree

Use independent increments for Poisson processes, solve a boundary-value
equation for expected diffusion exit times, and solve \(\pi P=\pi\) plus
normalization for finite chains.

## Theorem preconditions

Check initial state, time homogeneity, stopping-time admissibility, boundary
conditions, irreducibility claims, and conditional-event probability.

## Common errors

Do not confuse a Poisson process with one Poisson variable, assume stationarity
without solving it, or omit both exit boundaries.

## Counterexample checklist

Check time zero, absorbing states, row/column conventions, probability sum one,
and asymmetric interval endpoints.

## Compatible check types

Use `reasoning`, `boundary`, `theorem_preconditions`,
`symbolic_equivalence`, and `answer_type_check`.

## Answer normalization

Return probabilities as exact fractions and stationary distributions as an
ordered vector in the stated state order.

## Trace step guidance

Expose process property, conditioning/generator equation, boundary or
normalization equations, and exact result.
