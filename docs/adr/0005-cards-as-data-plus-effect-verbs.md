# ADR 0005: Cards as data plus effect verbs

Date: 2026-08-10
Status: accepted

## Context

The usual way a hobby Magic simulator dies is modelling cards as fixed fields —
"a creature has power, toughness, and a keyword set". That works until the
hundredth card, at which point every new mechanic is a new field and the model
must be rewritten. "Eventually the entire game" is unreachable from there.

## Decision

A card is **printed data plus a tuple of `Effect(verb, params)`**, parsed from
oracle text. Growing fidelity means implementing more verbs, never adding fields.

Parsing is rules-based over Magic's templated wording, with one governing rule:

> every clause is either matched to a verb or recorded as unparsed.

`Parsed.coverage` is the fraction matched. A card below 1.0 is one the engine
must not pretend to understand.

Corpus-wide result over all 35,139 cards:

```
fully parsed    22,280  (63.4% of cards)
clauses matched 54,264/71,935  (75.4%)
```

`examples/effect_coverage.py` prints the remaining gaps grouped by clause shape,
ordered by how many cards each would unlock. That list is the work queue.

## What the measurement taught

The first honest measurement read 42.8% of cards. Roughly half the apparent
failure was **not a parsing gap at all**: `Equip {1}`, `Ward {2}`,
`Cycling—Pay 1 life` are keyword abilities — named rules, not effects — and the
keyword detector rejected them because it required bare words and choked on the
`{N}`. Fixing the detector moved coverage to 63.4% without teaching the parser a
single new effect.

This is the argument for reporting coverage rather than eyeballing output: the
largest "gap" was a measurement artifact, and no amount of reading sample cards
would have revealed its size.

A second bug of the same shape: text normalisation collapsed *all* whitespace
including newlines, and newlines are what separate abilities. Goblin Guide's
`Haste` merged into the trigger below it and both were lost.

## Corollary: package facades hold no code

Adding the engine gave `manalab.engine` a four-module import cycle, found by
shipyard's topology view and confirmed with a Tarjan pass. The cause was
submodules importing through their own package facade
(`from manalab.engine import mana`), which drags `__init__.py` — itself importing
`game` and `agents` — into the graph.

Rule, now enforced by two tests: **a package `__init__` re-exports and defines
nothing, and submodules import siblings directly.** `evaluate/__init__.py` was
split into a facade plus `result.py` to comply.

Worth recording because the cycle was invisible from any single file, passed 190
tests, and was caught by a tool built for a different purpose.

## Consequences

- The engine implements a *subset* of verbs and reports the rest. Today that
  subset is empty: spells resolve doing nothing, loudly.
- Parsed effects describe what a card **says**. What it *means* in a game is the
  engine's job, and the two are deliberately separate.
- Scryfall's `keywords` field is trusted for keyword recognition, with a
  supplementary list for parameterised keywords it sometimes omits.
