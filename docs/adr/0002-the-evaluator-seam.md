# ADR 0002: The evaluator seam

Date: 2026-08-08
Status: accepted

## Context

The stated goal is deckbuilding search now and "eventually the entire game". Those
two want opposite things from a simulator: search wants millions of cheap games,
real Magic wants faithful ones. Building for either alone guarantees a rewrite.

## Decision

One boundary, and everything is organised around it:

```
evaluate(decklist, n_games, seed) -> EvalResult
```

Above the line lives search: optimisers, simulation-budget allocation, variance
reduction, statistics. **None of it knows how a game of Magic works.** Below the
line lives the game model.

Enforced mechanically in `tests/test_architecture.py`, not by intention:

| Layer | Package | May import |
|---|---|---|
| L0 | `cards` | — |
| L1 | `game` (goldfish) | `cards` |
| L1 | `engine` (rules) | `cards` |
| L2 | `evaluate` | `cards`, `game`, `engine` |
| L3 | `search` | `cards`, `evaluate` |

`search` may never import `game` or `engine`. If an optimiser needs to know about
lands, that knowledge belongs in a metric the evaluator returns.

## Consequences

- Upgrading fidelity is a new `Evaluator` implementation and *zero* changes to
  search. This is the property the whole project rests on.
- Optimisers work on integer count-vectors over a `CandidatePool` and read scores
  back. They never see a `Card`.
- Evaluators must be pure in `(deck, seed)`. Common random numbers depend on it,
  and CRN is what makes search affordable (ADR 0004).
- The cost: metrics are the only channel between the layers, so a question search
  wants to ask must first be expressible as a number the evaluator computes. That
  friction is deliberate.
