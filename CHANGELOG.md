# Changelog

All notable changes to manalab are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

Everything below is the initial build. The repo has no commits yet — the first
one, and the version cut, are deliberately left for review.

### Added — card database

- **Scryfall bulk ingest → DuckDB.** Keyless, stdlib-only download of the
  `oracle_cards` export (24.5 MB compressed) loaded straight from `.jsonl.gz`;
  35,139 cards. `manalab fetch | build | info`. `data/` is a build artifact and
  is gitignored.
- **Card characteristics** — power, toughness, loyalty, keywords, colors, color
  identity. Printed P/T stays a *string* because Magic has `*` and `1+*`;
  `base_power` returns `None` for those rather than inventing a number.
- **Mana costs** as generic plus a sequence of colour-sets, which collapses plain
  and hybrid pips into one representation. Monocoloured hybrid and Phyrexian are
  flagged `approximated` rather than silently simplified.
- **Payment solver** (`cards/payment.py`) — bipartite matching, because counting
  sources per colour is wrong whenever duals exist: a W/U dual plus a Mountain
  cannot pay `{W}{U}`, and naive counting says it can.
- **Effect-verb parser** (`cards/effects.py`) — 40 verb patterns over oracle
  text, producing `Effect(verb, params)`. Every clause is either matched or
  recorded as unparsed; nothing is skipped. Corpus coverage: **63.4% of cards
  fully parsed, 75.4% of clauses matched**. `examples/effect_coverage.py` prints
  the remaining gaps grouped by clause shape, ordered by cards unlocked.
- **Decklist text format**, `CandidatePool` for vector-valued deck search, and
  `all_cards`/`sample` for corpus work.

### Added — goldfish model (`manalab.game`)

- Shuffling, London mulligans with pluggable keep/bottom policies, hand-aware
  land sequencing, greedy curve-out, and consistency metrics.
- **Validated against Frank Karsten's colored-source tables**
  (`examples/karsten_validation.py`): 14 sources → 90.7% for a turn-1 single pip;
  12 sources → 94.0% for a turn-3 pip conditional on three lands. Derived
  independently of this tool, so agreement is real evidence.
- Honest reporting: `scan_unmodeled` names every card whose text the model
  ignores or approximates, and `manalab sim` prints it.

### Added — rules engine (`manalab.engine`)

Peer to the goldfish model, not its replacement (ADR 0003).

- Seven zones with private/shared/ordered/hidden distinctions; `GameObject`
  carrying per-instance state; players with life, land drops and loss conditions.
- **Zone movement as the single mutation primitive.** A card changing zones
  becomes a new object (CR 400.7) — the old id is deleted, so stale references
  raise instead of mutating a ghost.
- Twelve-step turn structure, priority passing, the stack, sorcery-speed timing,
  combat with attackers/blockers/simultaneous damage, and state-based actions
  applied to a fixed point.
- `Agent` protocol with passing / random / curve baselines. The engine enumerates
  legal actions and asks an agent to pick one, so an agent *cannot* make an
  illegal play and any rules violation is an engine bug.
- Games run end to end and are reproducible by seed. The mirror match gives the
  player on the play 57%, which is the right direction and magnitude.

### Added — deckbuilding search (`manalab.search`) — now dormant

Phases 0–2 of `docs/M2_PROMPT.md` landed and are green; work is parked in favour
of the engine. It sits entirely above the evaluator seam and constrains nothing.

- Reproducible harness: `Problem`, `Oracle`, `Trace`, `BudgetMeter`, DuckDB
  results store. Budget is counted in simulated games, never wall clock, and
  overruns raise. Identical seeds produce byte-identical trace digests.
- Ground-truth tiers: an analytic problem whose optimum is exact by
  hypergeometric, plus brute-forceable and realistic tiers.
- **Common random numbers measured, not assumed**: 5.8× variance reduction at one
  swap, decaying to 1.8× at six. Paired comparison, power analysis, and a
  `verdict()` that abstains rather than guessing.

### Added — documentation

- `ARCHITECTURE.md` with a mechanically enforced layer contract.
- ADRs 0001–0005 in `docs/adr/`.
- `ATTRIBUTION.md` — Scryfall terms, WotC Fan Content Policy, and the note that
  Moxfield forbids scraping but grants access on request.

### Fixed

Bugs found while building, each of which would have produced confident wrong
answers rather than a crash:

- **Fetchlands produced no mana.** Scryfall reports empty `produced_mana` for
  them — literally true, practically useless — so they simulated as dead lands.
  Now approximated as untapped duals, and reported as an approximation.
- **Shocklands always entered tapped.** Their wording is "you may pay 2 life. If
  you don't, it enters tapped", with no "unless", so a tapland regex caught them.
- **Land sequencing ignored the hand.** Holding a Mountain, a Plains and a `{R}`
  one-drop, the sim played the Plains 36% of the time. This invalidated every
  multicolour result. Fixing it moved a burn deck's turn-3 curve-out from 0.49 to
  0.83.
- **`--target` measured the wrong thing** — whether the greedy policy *chose* to
  cast a card, not whether it was castable. Castability is now tracked separately
  and is what mana-base questions report.
- **Random deck sampling could not reach the optimum.** Dealing copies to cards
  with room concentrates on the centre of the simplex; on a 3-card pool it reached
  300 of 861 decks in 20,000 draws and never once found the optimum. Replaced with
  exact uniform sampling via a DP over feasible completions (χ² = 807 on 860 df).
- **Random streams overlapped.** Stream indices were used as raw seed offsets, so
  streams 1 and 2 shared 399 of 400 games and an "independent" comparison was
  secretly paired.
- **Every optimiser run shared one stream**, so replicating across seeds varied
  the optimiser's choices but replayed identical games.
- **Newlines were collapsed during text normalisation**, destroying the line
  structure that ability parsing depends on.
- **Parameterised keywords counted as parser failures.** `Equip {1}`, `Ward {2}`
  are named rules, not effects; the detector required bare words. Fixing it moved
  card coverage 42.8% → 63.4% — the largest apparent gap was a measurement
  artifact.
- **A four-module import cycle in `manalab.engine`**, surfaced by shipyard's
  topology view and confirmed with a Tarjan pass. Caused by submodules importing
  through their own package facade. Package `__init__` files now re-export and
  define nothing; two tests enforce it.
- **`PassingAgent` crashed declaring blockers** — "do nothing" is not always
  `Pass`, since blocker declaration must be answered.

### Known gaps

- **Spells resolve doing nothing.** The engine has no verb execution yet, so a
  burn deck takes 19 turns instead of 9. `GameResult.unmodeled` names every card
  it failed. This is the next piece of work.
- No triggered or activated abilities, first strike, multi-blocks, flash, or
  continuous effects.
- Engine mana treats every source as producing exactly one mana; Sol Ring and
  friends are undercounted and reported.
- The goldfish model has no opponent and cannot measure whether a deck wins.
