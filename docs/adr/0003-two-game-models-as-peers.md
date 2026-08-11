# ADR 0003: Two game models as peers, not a succession

Date: 2026-08-10
Status: accepted

## Context

`manalab.game` is a goldfish model: one player, no opponent, no interaction. It
answers consistency questions in microseconds and is validated against Frank
Karsten's colored-source tables.

Building the rules engine raised the obvious question: is `engine` the successor
to `game`, to be deleted once the engine works?

## Decision

**They are peers.** Both sit behind the `Evaluator` protocol (ADR 0002), and a
caller picks fidelity by choosing an evaluator rather than by changing code.

**Neither may import the other**, enforced by a test.

## Rationale

They answer different questions at costs three orders of magnitude apart. A
20,000-game consistency sweep takes about a second in the goldfish model. The
same sweep through a rules engine is a coffee break. Deleting the fast model to
"consolidate" would make every mana-base question expensive for no gain in
answer quality, because the rules engine does not know anything extra about
whether you hit your third land drop.

The import ban is the load-bearing part. The goldfish model is full of stated
approximations — fetchlands modelled as untapped duals, one mana per source, a
greedy curve-out policy. Those are *correct* choices there, and *bugs* in a rules
engine. Sharing a helper between the two is how the approximations would leak,
and a wrong answer from a rules engine is far harder to notice than a wrong
answer from a sim that advertises its blind spots.

## Consequences

- Genuinely shared logic goes **down** into `cards`, not sideways. The mana
  payment solver moved from `game/mana.py` to `cards/payment.py` for exactly this
  reason: bipartite matching over a `ManaCost` knows nothing about turns or
  zones, so it is a property of costs and belongs in L0.
- Two models must be kept in agreement on the questions both can answer. That is
  a feature — a disagreement between them is a bug in one of them, and the
  goldfish model has external validation the engine does not.
- `game` is described in the README as "disposable", meaning cheap to replace,
  not scheduled for deletion.
