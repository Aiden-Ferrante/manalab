# ADR 0006: extend effects.py rather than benchmark external parsers

Date: 2026-08-11
Status: accepted

## Context

Follows [ADR 0005](0005-cards-as-data-plus-effect-verbs.md), which established
cards as printed data plus `Effect(verb, params)` and set the governing rule that
every clause is either matched to a verb or recorded as unparsed. This decides
whether the *next* cycle grows that parser or measures alternatives to it first.

The card-database cycle was originally scoped as a **benchmark**: wrap three
existing open-source Oracle-text parsers (CubeArtisan's `magic-card-parser`,
Zannick's Demystify, melvinzhang's `oracle-parser`) behind a uniform adapter,
run them over the corpus, and produce a decision document answering *extend an
existing parser, or start clean?*

That framing assumed a clean start. It is the right question when you have
nothing, and the out-of-scope list it came with — no parser, no IR, no engine —
is the right discipline for a project that would otherwise build before
measuring.

manalab is not that project. It already has:

- `cards/effects.py`, 389 lines, turning oracle text into `Effect(verb, params)`
  tuples, with a stated rule that *every clause is either matched to a verb or
  recorded as unparsed*, and per-card `coverage` reporting.
- `cards/bulk.py`, a working Scryfall bulk ingest — resolves
  `jsonl_download_uri` with a `download_uri` fallback, sets a descriptive
  User-Agent, keeps files gzipped because DuckDB decompresses by extension.
- An engine that consumes those verbs, a goldfish simulator, and a parked search
  layer above an `Evaluator` seam.

A measured baseline over the current corpus:

```
corpus            35,139 cards
  no oracle text   1,236
  fully parsed    22,280  (63.4%)
  clauses matched 54,264/71,935  (75.4%)
largest remaining gaps: 10,998 distinct unmatched clause shapes
```

63.4% of cards fully parsed is not a starting position that a benchmark would
improve on. It is a position a benchmark would *measure against*, and the
comparison would cost the cycle without changing what gets built next.

## Decision

**Extend `effects.py`. Do not benchmark the external parsers this cycle.**

The decision document the benchmark existed to produce is answered here, by the
existence of a working parser at 63.4% coverage with an ordered gap list: extend.

The benchmark is not rejected on merit — it is deferred. If `effects.py` stalls
against a class of cards it structurally cannot express, comparing its output
schema to three others becomes the cheapest way to find a better
representation, and that is the moment to run it.

## Consequences

**The gap list is the work queue.** `examples/effect_coverage.py` already groups
unmatched clauses by shape, so "deals 3 damage" and "deals 5 damage" count once.
It is ordered by how many cards each missing pattern unlocks. That ordering, not
a coverage target, is what the next cycles pull from.

**Coverage will get worse before it gets better, and that is correct.** The
database is missing text it should have:

- All 886 null-text cards in the loaded table carry `card_faces` — every
  transform, adventure, split, modal DFC, flip and prepare card. 100% of the
  nulls, one cause:

  ```
  transform 401 · adventure 170 · split 137 · modal_dfc 100 · prepare 55 · flip 21
  ```

- The 3,484-row difference between the file (38,623) and the table (35,139) is
  **not** a gap: `store.build` excludes 2,676 art-series and 808 token entries on
  purpose, and every playable card loads. Verified against the raw file — no card
  has a null `type_line`.
- A separate 350 cards are genuinely vanilla: loaded, and with no text to parse.

*(Corrected 2026-08-11. An earlier draft of this ADR said 3,212 cards hide text in
`card_faces`. That figure was counted over the whole bulk file including the tokens
and art series the loader drops, and overstated the real gap by 3.6×.)*

Fixing the schema will hand `effects.py` thousands of cards of text it has never
seen. The 63.4% figure will drop. **Anyone treating it as a baseline to beat will
misread that drop as a regression when it is the opposite** — it is the parser
finally being asked the whole question.

**Order is therefore fixed: faces first, then parser.** Extending `effects.py`
against a corpus that silently omits every multi-face card would tune it on a
biased sample and report a coverage number that flatters.

**Coverage is not a score to maximise.** `effect_coverage.py` already says this:
a card below 1.0 is a card the engine must not pretend to understand. The
purpose of measuring is to know which cards those are.
