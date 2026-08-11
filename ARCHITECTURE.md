# Architecture

manalab is a **deckbuilding search engine** that happens to contain a Magic simulator.
That ordering is the whole design. The simulator is the disposable part.

## The one boundary that matters

```
evaluate(decklist, n_games, seed) -> EvalResult
```

Above this line lives search: optimizers, simulation-budget allocation, variance
reduction, statistics. None of it knows how a game of Magic works.

Below it lives the game model. Today that is a ~500-line abstract goldfish
simulator. Later it may be a full rules engine, or a subprocess wrapping Forge.

If this boundary holds, upgrading fidelity is a new `Evaluator` implementation
and *zero* changes to search. If it leaks, the eventual rules engine is a rewrite.

## Layers and dependency direction

Dependencies point strictly downward. This is enforced mechanically by
`tests/test_architecture.py`, not by good intentions.

| Layer | Package | May import | Responsibility |
|---|---|---|---|
| L0 | `manalab.cards` | — | Card data. Scryfall/MTGJSON ingest, DuckDB store, `Card`, `ManaCost`, `Effect`, `Decklist`, `CandidatePool`. Knows nothing about games. |
| L1 | `manalab.game` | `cards` | **Goldfish model.** One player, no interaction. Fast, shallow, disposable. |
| L1 | `manalab.engine` | `cards` | **Rules engine.** Zones, turn structure, priority, the stack, two players. Slow, deep, the long-term home. |
| L2 | `manalab.evaluate` | `cards`, `game`, `engine` | **The seam.** `Evaluator` protocol + implementations. Turns a decklist into numbers. |
| L3 | `manalab.search` | `cards`, `evaluate` | Optimizers and budget allocation. **Must never import `game` or `engine`.** |

`game` and `engine` are peers, not a succession. They answer different questions
at different costs, and both sit behind the same `Evaluator` protocol, so a
caller picks fidelity by choosing an evaluator rather than by changing code.
**Neither may import the other** — sharing helpers would let the fast model's
approximations leak into the real one, which is the single hardest class of bug
to notice once it happens.

`search` importing either is the failure mode to watch for. If an optimizer needs
to know about lands, that knowledge belongs in a metric the evaluator returns.

## What each layer hides

- **`cards`** hides where card data came from. Swapping Scryfall for MTGJSON
  changes one module.
- **`game`** hides the rules. It exposes per-game *records*, not game state.
  Nothing outside `game` may hold a reference to a live game.
- **`evaluate`** hides fidelity. A caller cannot tell whether results came from
  the abstract sim or a rules engine, except by reading `EvalResult.evaluator`.
- **`search`** hides the optimization strategy.

## Cards are data plus effect verbs

Cards are never modeled as fixed fields like "a creature with power and
toughness". They are Scryfall data plus a tuple of `Effect(verb, params)`.

The abstract sim implements a small subset of verbs and treats unknown verbs as
inert — honestly and loudly, via `EvalResult.unmodeled`. Growing fidelity means
implementing more verbs, not rewriting the model. This is the only reason
"eventually the entire game" is reachable rather than a second project.

## State

Almost none. Two exceptions, both explicit:

- **The card store** (`data/cards.duckdb`) is a build artifact. Rebuildable from
  Scryfall in one command. Never edited by hand, never committed.
- **A running game** is mutable, lives inside one function call in `game`, and is
  destroyed before its record is returned.

Everything else is frozen dataclasses. Simulations are pure functions of
`(decklist, seed)`, which is what makes common random numbers possible.

## Randomness

Every stochastic entry point takes an explicit `seed: int`. No module ever calls
the global `random` module. This is not tidiness — comparing two decks on the
*same* shuffle seeds is the variance reduction that makes search affordable, and
it only works if seeding is total.

## Non-goals

- Playing Magic against a human. This is a batch research tool.
- Rules correctness in v1. The sim's assumptions are documented in
  `game/goldfish.py`; unmodeled cards are reported, never silently approximated.
- Win rates in v1. The abstract sim has no opponent, so it measures consistency
  and clock, not "does this deck win". Optimizing a proxy you can defend beats
  optimizing a win rate against a weak AI.
