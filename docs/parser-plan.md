# The parser: where it stands, and the plan to make it work well

Date: 2026-08-15 · Status: living document

## The contract, restated

ADR 0005's rule is the whole design: **every clause is matched to a verb or
recorded as unparsed.** A wrong parse is worse than no parse, because
`fidelity` trusts `unparsed` to decide what the engine may execute — a card
that reads as fully parsed while carrying dropped text is executed half-read,
and a search will find and exploit the gap.

## Where it stands (all measured, 2026-08-15)

The two mechanisms that broke the contract are fixed:

* **Keyword swallowing** — `_keyword_ability` absorbed 297 lines whole into an
  inert `param`. A parameter is now bounded (a number, a mana cost, or plain
  words — never a comma or period); everything else falls through to ordinary
  parsing and lands in effects or `unparsed`, honestly either way.
* **Intra-clause drops** — `Pattern.match` used `search`, so only the first
  occurrence per clause was seen and the unmatched remainder of a matched
  clause went nowhere. Every pattern now reports every occurrence *with its
  span*, and meaningful residue outside all spans lands in `unparsed`. This is
  what catches the class no coverage metric can see: "instead" (replacements),
  "for each" (multipliers), "target player" (dropped targets), "you may"
  (optionality executed as mandatory).

The scoreboard after the fix, on mono-green Commander (4,633 cards):

| | before | after |
|---|---|---|
| faithful, parser alone | 540 | **357** |
| faithful, with the Forge fallback | 578 | **409** |
| Forge disagreements on faithful cards (4 classes) | 53/0/18/3 | **0/0/0/0** |

The pool *shrank* and that is the point: 183 of the old 540 were being
half-executed. Every card the engine now plays, it plays whole — verified
against 30,931 independently hand-encoded scripts.

## Progress (2026-08-15, same day)

Items 1–5 landed in one pass; the Forge oracle held at 0/0/0/0 throughout.
Pool: 357 → 390, all of it honest recovery. The measured "you may" split:
267 cards admitted (upside-only), 3,180 still refused. Item 6 remains the
only open item, held closed by the residue tracker as designed.

## The plan, in order

Each item is sized by measurement, not estimate. The instrument stays ahead of
the work: `examples/forge_validation.py` must hold at 0 on its four classes,
and each item below adds its own class before the fix lands.

1. **Targeted draw/gain — "target player draws three cards."** The largest
   clean recovery: the pattern needs a target param and `resolve` already
   re-checks targets. Recovers the Ancestral Recall / Congregate class
   (~62 refusals) *correctly* rather than by refusal.
2. **"You may" as a real choice.** Either model the choice (an agent decision
   at resolution) or adopt greedy-yes as a *declared* approximation with its
   own fidelity reason, so punisher cards ("any player may…") stay refused
   while self-only upside ("you may draw") is admitted. Measure the split
   first.
3. **Bound the greedy captures** — `untap`, `sacrifice`, `tap` capture
   `[^.,]+` and swallow static prose ("more than two permanents during their
   untap steps"). Bound them the way keyword params are bounded, then
   implement `untap`/`sacrifice` as verbs; their activation costs are already
   gated by `activation.parse_activation_cost`.
4. **Loyalty costs** — 873 abilities where `+1:`/`−X:` is not recognised as an
   activation cost (U+2212, and no braces). Parse them as activated abilities
   with a loyalty cost; the engine already stores loyalty counters.
5. **Coverage arithmetic** — the metric counts effects, not clauses (5,223
   phantom matches, 1,032 cards overstated). Does not affect execution; fix it
   so the number means what it says.
6. **Replacements and multipliers ("instead", "for each")** — last, because
   they need engine machinery (a replacement layer, a count model), not
   pattern work. Until then the residue tracker keeps every one refused.

## The standing rule

Never chase the pool number. Every accuracy fix so far has *shrunk* the pool
before growing it back honestly, and the retraction taught this project what
believing convenient numbers costs. The instruments — the golden set, the
Forge oracle, the L3 shadow-parser checks — run before and after every change
to this file's territory.
