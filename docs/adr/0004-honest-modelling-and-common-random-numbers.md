# ADR 0004: Honest modelling, and randomness as a design surface

Date: 2026-08-09
Status: accepted

## Context

Two problems that look unrelated and are not. Both are about a simulator lying
quietly.

**Blind spots.** No model covers 35,000 cards. A sim that silently ignores card
draw will systematically undervalue every deck full of cantrips, and search will
then systematically avoid cantrips. That is *bias*, not noise: more games will
never fix it, and nothing in the output would say so.

**Noise.** The objective is estimated by sampling, so every comparison between
two decks is a statistical test, whether or not it is written as one.

## Decision

### Nothing is approximated silently

Every layer reports what it could not represent, by name:

- `EvalResult.unmodeled` — cards the evaluator could not handle.
- `GameResult.unmodeled` — cards the engine resolved with no effect.
- `effects.Parsed.coverage` — the fraction of a card's clauses that parsed;
  every clause lands in either `effects` or `unparsed`.
- Approximations are reported *alongside* outright gaps ("fetchland,
  approximated as an untapped dual"), because "we modelled this, roughly" and
  "we ignored this" are both things you must know before quoting a number.

### Randomness is a design surface, not an implementation detail

- Every stochastic entry point takes an explicit seed. No module calls the
  global `random`.
- Streams are **indices mapped to disjoint seed blocks**, never raw seed
  offsets. Using the index directly makes stream 1 and stream 2 share every game
  but one, silently converting an "independent" comparison into a paired one.
- Each optimiser run seed gets its **own block of streams**, so replicating an
  experiment varies the games and not merely the optimiser's internal choices.
- Comparisons between decks are paired by default, and `compare.paired()`
  refuses misaligned samples rather than degrading to a wrong standard error.

## Measured consequence

Common random numbers were measured on the real simulator rather than assumed:

| decks apart | ρ | budget multiplier |
|---|---|---|
| 1 swap | 0.83 | **5.8×** |
| 2 swaps | 0.73 | 3.7× |
| 6 swaps | 0.43 | 1.8× |

The coupling decays with distance. That is a testable prediction about search:
local methods get a much larger effective budget than population methods at the
same nominal budget, because they compare near neighbours.

## Consequences

- Reports must separate conclusions about *optimisation* (which survive a
  fidelity upgrade) from conclusions about *Magic* (which are only as good as the
  model, and must carry their `unmodeled` caveat).
- Never write "this deck is better" when the measurement says "this deck is more
  consistent". The goldfish model has no opponent and cannot answer the first.
