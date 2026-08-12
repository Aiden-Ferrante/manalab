# manalab

Deckbuilding search over Magic: the Gathering, with a swappable game model.

The goal is to test strategy theories by simulation. The design bet is that for
deckbuilding search, **the objective function matters more than simulator
fidelity** — so the simulator sits behind a protocol and is meant to be replaced,
while the search machinery above it is built to last. See [ARCHITECTURE.md](ARCHITECTURE.md).

## Status

Current focus: **the search ladder and the rules engine.**

- **M0 — card data spine.** Done, and now *exhaustively verified*: every card,
  face and field checked against Scryfall's own export (`examples/verify_exact.py`,
  zero diffs), faces loaded so no card is silently textless, per-face type
  classification queryable in SQL.
- **M1 — evaluator seam + goldfish sim.** Done. Mulligans, correct colored-mana
  payment, hand-aware land sequencing, consistency metrics; Karsten's published
  colored-source tables reproduced end to end.
- **M2 — deckbuilding search.** *Active.* The problem is stated precisely in
  `docs/search-problem.md`; the architecture is decided by a standing
  variance-decomposition experiment rerun at every objective rung (ADR 0007).
  Three rungs on record — identity's share of variance moved 13.4% → 53.6% as
  objectives learned to see spells — with bilevel mana fitting and synergy
  ports as permanent fixtures. Narrative: `docs/campaign-2026-08-11.md`.
- **M5 — rules engine.** *In progress.* Real game state: zones, turn structure,
  priority, the stack, two players. Grown one effect verb at a time. Now also
  the calibration path for synergy weights — λ is a declared prior until an
  evaluator can watch a sacrifice resolve.
- **M6 — card database depth.** Effect-verb parsing at 65.6% of cards with the
  unparsed remainder named and ranked; precision smells at 2.11% with a 30-card
  human audit pending (`reports/audit_effects.md`).
- **M3 — validation against 17Lands.** Not started.
- **M4 — a Forge-backed evaluator.** Not started. Needs JDK 17+.

## Setup

```bash
uv venv && uv pip install -e '.[dev]'
```

## Use

```bash
manalab fetch --dry-run          # check the download size first
manalab fetch                    # Scryfall oracle_cards bulk export
manalab build                    # load it into data/cards.duckdb
manalab info

manalab sim decks/burn.txt -n 20000 --target "Goblin Guide:1"
```

`data/` is a build artifact and is gitignored — rebuild it rather than copying it.

## Validation

`examples/karsten_validation.py` reproduces Frank Karsten's colored-source
tables, which were derived analytically and independently of this tool. It is
the strongest external check available on the mana model, exercising card
parsing, mulligans, land sequencing and the payment solver together:

```
 R sources   1-drop t1   3-drop t3 | 3 lands
        12       0.852              0.940   <- Karsten: 12 for t3
        14       0.907              0.969   <- Karsten: 14 for t1
```

Run it after touching anything in `manalab.game`. It found two real bugs the
first time it ran — land sequencing that ignored the hand, and fetchlands parsed
as producing no mana.

## What the simulator can and cannot tell you

It plays solitaire. There is no opponent, no combat, no interaction. It answers
*consistency and clock* questions:

- how many lands should this deck play
- how often does the mana base actually produce {B}{B} on turn three
- what does a given mulligan rule cost or buy
- how much does a tapland hurt this specific curve

It cannot tell you whether a deck wins. It also cannot represent card draw,
tutors, scry, fetchlands, or cost reduction — so `manalab sim` prints every card
in your deck whose text it had to ignore. Read that list before believing the
numbers. A deck full of cantrips will simulate as worse than it is.

## Attribution

Card data from [Scryfall](https://scryfall.com), used under their terms and the
Wizards of the Coast Fan Content Policy. Not affiliated with or endorsed by
Wizards of the Coast. See [ATTRIBUTION.md](ATTRIBUTION.md).
