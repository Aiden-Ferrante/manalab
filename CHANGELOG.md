# Changelog

All notable changes to manalab are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

Deckbuilding search closes the loop: a genetic algorithm scored by games the
rules engine actually plays. The notebook
`notebooks/genetic_deck_search.ipynb` runs it end to end with the numbers below.

### Added

- **`engine/triggers.py` — triggered abilities, and the events they watch.**
  Magic's commonest ability shape is "when something happens, do this" — 14,481
  triggered abilities in the corpus against roughly 18,000 activated-or-spell
  ones — and the engine had no notion of an event at all. A creature with an
  enters-the-battlefield trigger resolved onto the battlefield and did nothing,
  silently, forever.

  `state.move` is the single choke point every zone change passes through, so
  events are recorded there; `_collect_triggers` puts them on the stack after
  state-based actions and before anyone acts (CR 117.5), so a trigger is a real
  object that can be responded to. It resolves and ceases to exist — the
  permanent stays put, which needed `state.cease`, because `move` would have put
  a second copy of the source card in a graveyard.

  Scope is the self-referential enters/dies family: ~3,992 + ~481 abilities,
  over a quarter of every trigger printed. Everything else is **refused by name**
  — upkeep, attack, combat-damage and the "another permanent you control" family
  all make their card unfaithful rather than being ignored.

  This also required `Card` to carry `abilities`, not just flattened `effects`.
  The parser always knew a draw was a trigger; `Parsed.effects` flattened it away
  and `Card` only carried the flattened view, so by the time the engine saw a
  card the difference was gone. Same information-loss shape as `unparsed`.

  **Pool effect: mono-green Commander 233 → 270 faithful cards.** Modest on
  purpose — the spine is built, but most triggers' *effects* use verbs that do
  not exist yet (`search_library`, `create_token`, `grant_ability`), so Craterhoof
  Behemoth, Sakura-Tribe Elder and Eternal Witness are all still refused. The
  verbs are what convert this, and they are next.

- **`cards/formats.py` — constructed formats as first-class objects.** "The
  format" used to be the string `"modern"` threaded through `mono_color`, with
  the construction rules scattered as constants: 60 in `pool.partition`, a
  four-copy `default_max` on `CandidatePool` whose docstring already said "1 in
  singleton" with nothing supplying it, and a basic-land exemption written out
  twice. Commander could not be expressed at all.

  A `Format` owns legal pool, deck size, copy limit and starting life. Seven
  presets: Standard, Pioneer, Modern, Legacy, Vintage, Pauper, Commander.
  `mono_color(store, "U", fmt=COMMANDER)` now returns a singleton pool at 100
  cards with basics uncapped, without the caller restating any of it. Strings
  still work, so existing examples are unchanged.

  **Restricted is now a copy limit rather than an exclusion.** `legal_in`
  filtered on `= 'legal'`, so Vintage silently lost the 52 cards that define it —
  Black Lotus, Ancestral Recall, Time Walk. The new `store.legality_in` keeps the
  status, and a restricted card lands at one copy in the pool. It also reads
  formats through `json_extract_string` rather than `legalities[?]`, which is the
  same bind-time failure the loader predicate had.

  `violations()` takes a legality map rather than a store, so checking a deck
  costs no query and the tests need no corpus.

### Fixed

- **The parser stopped half-reading cards** (`cards/effects.py`). Two
  mechanisms broke ADR 0005's contract that every clause is matched or recorded
  unparsed. `_keyword_ability` swallowed 297 lines whole into an inert `param`
  ("Scry X, …, then draw three cards" was recorded as scry, coverage 1.0);
  a parameter is now bounded — a number, a mana cost, or plain words, never a
  comma or period. And `Pattern.match` used `search`, so only a clause's first
  match was seen and the unmatched remainder of a matched clause went nowhere;
  patterns now report every occurrence with its span, and meaningful residue
  lands in `unparsed`. That residue is what catches the class no coverage
  metric can see: "instead", "for each", "target player", "you may".

  **The pool shrank from 540 to 357 and that is the fix working**: 183 cards
  were faithful-on-paper while being executed half-read — Life Goes On gained
  12 life instead of 4, Congregate paid the caster, Ancestral Recall drew for
  the wrong player. All refused now. Forge disagreements on faithful cards:
  53/0/18/3 across the four classes → **0/0/0/0** over 30,931 scripts. The
  road back up is `docs/parser-plan.md`, ranked and measured.


- **Asymmetric pump was executed with the wrong arithmetic** (`engine/resolve.py`).
  Pump was modelled as counters, which are symmetric by construction, so the two
  halves were collapsed with `max(power, toughness)` and applied to both. Nameless
  Inversion (+3/-3) resolved as a permanent +3/+3 buff instead of killing its
  target; Chelonian Tackle (+0/+10) made a 12/12; every all-negative shrink was a
  silent no-op; Agony Warp did nothing at all. **43 of 102 pump cards in the
  searchable pool were wrong, and `fidelity` called every one of them faithful.**
  `GameObject` now carries `power_mod`/`toughness_mod`, applied independently and
  cleared in the cleanup step — so "until end of turn" now means what it says,
  rather than lasting the rest of the game. Verified against Forge's hand-encoded
  scripts: **0 pump amount mismatches across 30,931 cards.**

- **`fidelity` could not see text the parser never read** (`engine/fidelity.py`,
  `cards/model.py`, `cards/effects.py`). The non-permanent branch asked
  `resolve.unsupported`, which inspects only the effects that *did* parse, and
  `with_effects` discarded `Parsed.unparsed` — so unmatched clauses were invisible
  to the one mechanism whose job is to notice them. Pact of Negation entered the
  blue pool as a free, drawback-free counterspell because "pay {3}{U}{U}, or you
  lose the game" was dropped. `Card` now carries `unparsed`, and a card with any
  is refused. 90 of 819 faithful cards were affected.

- **"you" was modelled as "any player"** (`engine/targets.py`). `legal_targets`
  returned every player, so a card's own drawback became a free choice and the
  pilot redirected it every time — Sarkhan's Rage aimed its self-damage at the
  opponent. New `TargetKind.CONTROLLER` resolves to the caster alone.

### Changed

- **The corpus is now cards you can actually play**: 35,142 → **31,878**. The
  store keeps a card only if some paper format lists it as `legal` or
  `restricted`. That removes 2,377 rows legal nowhere — Un-sets, Mystery Booster
  playtest cards, and 589 objects that are not cards at all (207 planes, 107
  vanguards, 102 schemes, 87 emblems, 50 tokens, 20 hosts, 14 augments) — plus
  887 digital-only Alchemy rebalances, which no paper deck can contain and which
  collide on name with the cards they rebalance. Banned-but-real cards stay:
  Black Lotus, Chaos Orb and Shahrazad all survive on another format. **Zero
  modern-legal cards are dropped**, verified.

  The rule had been written out three times — the `cards` table, the `faces` CTE,
  and `verify_exact.py` — so it is now one `_PLAYABLE` predicate plus one
  `is_playable()` for callers holding raw JSON, both driven by `PAPER_FORMATS`.
  Formats are read via `json_extract_string` rather than as struct fields,
  because a missing key is a *bind-time* error that kills the whole build.

### Added

- **`cards/forge.py` + `examples/forge_validation.py`** — the first external
  check on what a card *means*, rather than on what it says. Forge publishes
  ~33,700 cards as verb plus named parameters; we diff our `Effect(verb, params)`
  against theirs. Covers 100% of modern-legal cards. It reproduces, mechanically
  and at corpus scale, the defects a 43-card hand-written golden set found: 53
  faithful cards carrying an effect we never encoded, 53 asymmetric pumps, 20
  dropped target players, 3 flattened divided-damage spells. The scripts are
  GPL-3.0 and stay in gitignored `data/` — read, never redistributed (ADR 0008).

- **Combat keywords** (`engine/combat.py`) — flying and reach gating blocks,
  menace as a property of the whole assignment, trample spilling excess,
  deathtouch as one-point-is-lethal, first and double strike as two damage
  passes with state-based actions between them, and lifelink. 25 tests drive
  the rules directly against hand-built boards rather than through a game.
- **`engine/fidelity.py`** — the engine's account of its own blind spots, asked
  of a card *before* a game. One source of truth for which keywords are real,
  with a test that fails if the list claims one the engine never reads.
- **`evaluate/match.py`** — `MatchEvaluator`: win rate against a fixed gauntlet,
  draws at half a point, candidate alternating play and draw. Honours the
  `Oracle`'s game-*i*-at-seed-*s+i* contract, so racing and halving can splice
  extra precision onto a deck already measured.
- **`evaluate/pool.py`, `evaluate/gauntlet.py`** — the mono-green pool split into
  132 faithful cards and a labelled 3,064-card text tier, and five fixed
  archetypes built only from the faithful tier.
- **`search/genetic.py`** — tournament selection, uniform crossover over card
  counts, mutation, and `repair` back onto the legal simplex. Budget in games;
  elites re-measured on a fresh stream each generation rather than served a
  cached lucky score.
- **`Oracle.evaluate_many`** — the fitness fan-out across processes. Produces a
  byte-identical trace to the serial path (there is a test); 150,000 games in
  37s on 18 workers, 244 µs/game wall.

### Fixed

- **The defender could only ever declare one blocker.** `legal_blocks`
  enumerated single (blocker, attacker) pairs, so a wide board was unanswerable
  and "play the most creatures" won for reasons unrelated to Magic — precisely
  the artifact a deck search would have found and reported as a discovery.
  Assignments are now complete and multi-blocker, capped and reported when the
  board is too wide to enumerate.
- **Modal double-faced cards were admitted as faithful, textless 0-drops.**
  `is_land` is true for a `Sorcery // Land` type line, and a faced card carries
  blank top-level `oracle_text`, so every text check read "vanilla". Faced cards
  are now refused before anything reads either field.
- **`random_genome` smeared decks across the whole pool.** Twelve cards at four
  copies hold 48, not 60, so `repair` scattered the shortfall uniformly — the
  concentration the function existed to create was undone every call, and basic
  lands were buried. The chosen set now grows until it can hold a full deck.

### Changed

- `ARCHITECTURE.md`'s "no win rates" non-goal narrowed rather than dropped: the
  number exists now, and the caveat that it measures "beats this gauntlet under
  this pilot" travels with it.

- **`search/coevolve.py`** — populations that optimise against each other instead
  of a fixture, built against the three ways naive co-evolution lies: a hall-of-
  fame archive so opponents are sampled from every champion ever (forgetting),
  explicit intransitive-triple detection (cycling), and progress scored against
  the *previous* round's Nash mixture rather than the current champion (a moving
  objective). Nash by fictitious play, not replicator dynamics — replicator
  orbits forever on exactly the intransitive games this module exists to find.
  All 22 tests run against hand-built matrices with no game involved, via an
  `Arena` seam that keeps `search` free of game knowledge.
- **`examples/evolve_all_colors.py`, `examples/coevolve_colors.py`** — the
  five-colour ladder and the co-evolution tournament.
- **Seven walkthrough notebooks** (`notebooks/cards/`, `notebooks/engine/`,
  indexed in `notebooks/README.md`) — the card layer and the rules engine, hand
  by hand, stored with their outputs. Every claim is demonstrated by a printed
  result rather than asserted in prose, which is how one of them caught a broken
  demo: the illegal-action check ran with five-card libraries, so both players
  lost to drawing from an empty library before the agent was ever asked, and the
  cell proved nothing while appearing to pass.
- **Spells that do something** — `engine/targets.py` (a small target language,
  legal-target enumeration, and CR 608.2b re-checking on resolution) and
  `engine/resolve.py` (the verb dispatcher: `deal_damage`, `destroy`, `draw`,
  `gain_life`, `pump`). Instants and sorceries had resolved doing nothing since
  the engine existed.

  Two rules that make the difference between working and looking like it works:
  a card is refused **whole** if any verb or target on it is unsupported, because
  half-resolving "destroy target creature and draw a card" produces a game that
  looks legal; and a spell with no legal target **cannot be cast** (CR 601.2c),
  because otherwise removal gets cast into an empty board and reads as a play
  mistake rather than an engine bug.

  The target language recognises four phrases and refuses 353 others by design.
  `Doom Blade` is still refused — "target *nonblack* creature" is a restriction
  the engine cannot enforce, and guessing would make illegal plays look legal.

- **Counterspells** — a target kind for objects on the stack, and the
  `counter_spell` verb. The stack and priority already existed, so a counter cast
  in response really does resolve first and send its target to the graveyard
  without resolving (CR 701.5a). `spell`, `creature spell` and `noncreature
  spell` are understood; `spell unless its controller pays {N}` is refused,
  because the pay-or-not decision has nowhere to live yet.
- **Mass effects** — `destroy`/`deal_damage` over a whole board, as a *scope*
  rather than a target: "destroy all creatures" chooses nothing (CR 115.10), so
  it must not enumerate one castable option per creature. Mass `pump` is
  deliberately refused: pump-as-counters is a bounded lie for one creature and a
  permanent global anthem when applied to a board, which is a different card
  rather than an approximation of one.

### Fixed

- **The crude pilot would destroy its own creatures.** The engine offers one
  `CastSpell` per legal target and "target creature" includes your own board, so
  `CurveAgent`'s "cast the most expensive thing" picked a target arbitrarily.
  That is not an interestingly-bad play, it is a broken measuring instrument.
- **Targets were nearly filed under a dead object id.** A card changing zones
  becomes a new object (CR 400.7), so targets recorded against the card in hand
  are lost the moment the spell reaches the stack — every removal spell would
  have resolved untargeted, silently. Pinned by a test.
- **A duplicate champion label silently corrupted co-evolution.** `black` and
  `blue` both abbreviated to `B`; `score_against_mixture` treats a same-label
  opponent as a mirror and scores it 0.5 without playing it, so the two colours
  skipped each other's decks, one deck was written twice, and blue was reported
  as surviving in an equilibrium it held zero weight in. `Archive.add` now
  refuses duplicates, and the example uses Magic's own WUBRG codes.

- **`search/report.py`** — phase 7, interpretation. Means with spread across
  seeds, comparison against the standard error of the *difference*, and **tiers
  instead of rankings**: results the noise cannot separate are printed together
  rather than in an order. `examples/evolve_all_colors.py` now replicates by
  default (`--seeds 4`), and `--seeds 1` warns that it is producing a number with
  no error bar. The deck written per colour is the run *nearest the mean*, not
  the best — shipping the best run is the winner's curse in file form.
- **`examples/replicate_colors.py`** — paired A/B of two gauntlet configurations
  across seeds, reporting whether a difference exceeds the seed noise.

### Measured

- **Single-run tournament results were noise, and were reported as findings.**
  The five-colour spread was rerun after each engine change and narrated as a
  causal story — verbs opened the metagame, removal opened it further, sweepers
  closed it. The reported sequence was 0.538 → 0.527 → 0.412 → 0.379 → 0.609,
  steps of ≤0.13. Replication at 4 seeds per condition measured seed-to-seed
  noise at **±0.116** and the sweeper effect at **−0.006**. Every step was inside
  the noise. What survives replication: **black strongest (0.69 ± 0.06)**,
  **blue weakest (0.26 ± 0.07)**; the middle three are not ordered by the data.
  The engine work is unaffected — it is verified by unit tests against hand-built
  boards, not by tournament outcomes.
- Winner's curse on the champion: **0.980 in-sample → 0.841 held out** on 3,000
  fresh games from a disjoint stream.
- **Faithful pool by colour**: white 151, green 131, red 88, black 80, blue 63 —
  out of ~3,200 each. Every colour loses 730–960 instants and sorceries to the
  inert pile, so each arrives at the table stripped to its creatures.
- **The five champions, head to head**: black 0.778 > green 0.679 > white 0.448 >
  red 0.408 > blue 0.240. Black wins on twenty deathtouch creatures — a 1/1
  deathtoucher eats any body green can build, and no removal exists to break the
  wall. Partly legitimate (deathtouch really does answer big creatures; Vampire
  Nighthawk and Gifted Aetherborn are real cards) and partly artifact (everything
  that would punish it is an instant that resolves doing nothing). A 0.538 spread
  is the engine talking, not the colour pie.
- Generalisation: champion **0.871** against a *held-out* gauntlet of three
  archetypes the search never saw, versus **0.749** for the best hand-built
  gauntlet deck — so the search is not merely angled at its training opponents.
- Initialisation dominates operators at this budget: cold start reaches **0.749**
  held out, seeding 25% of the population from a hand-built deck reaches
  **0.837**, and the hand-built start deck itself scores **0.780**. A cold start
  spends its budget rediscovering that lands exist.

## [0.2.0] — 2026-08-11

One day, two arcs — the card database made exact, and the deck-search ladder.
The full narrative with every number lives in `docs/campaign-2026-08-11.md`;
this is the ledger.

### Added

- **A `faces` table** — one row per printed side, synthesised face 0 for
  single-faced cards, so every card has at least one face and nothing downstream
  branches on layout. The parser reads every face under its own name (the text
  of Fire says "Fire", not "Fire // Ice"), which surfaced 886 previously
  unreachable card texts.
- **`face_types` classification** — supertypes, card types, subtypes and
  refused-to-guess unknowns per face, in the database (one GROUP BY away) and on
  the model (`Card.card_types`, union across faces). Nine unknowns in 36,030
  faces, all Un-set jokes.
- **Exhaustive verification** (`examples/verify_exact.py`) — every card, every
  face, every field against Scryfall's own export: zero diffs; derived-field
  invariants checked (zero attested producers invisible); exit code is the
  contract.
- **Fetch provenance** — downloads record updated_at/sha256 in a sidecar and the
  skip compares against it; "already current" and "downloaded" are now different
  messages, because "done" covering both is how a three-day-stale file hid.
- **The search ladder**: `search-problem.md` (the problem stated precisely),
  `composition_variance.py` (the standing architecture experiment, ADR 0007),
  `manafit.py` (bilevel basics fitting behind `FittedEvaluator`),
  `ports.py` (provide/require synergy ports, bottleneck score, injected as a
  zero-variance metric), objectives `THROUGHPUT` and `THROUGHPUT_SYNERGY`, and
  `composition_search.py` (CRN-paired hill climb on the simplex). Identity's
  variance share moved 13.4% → 32.3% → 53.6% across the three rungs.

### Fixed

- **Textless was conflated with unread** — 886 face-carrying cards counted as
  parsing successes the parser had never seen a word of. Coverage moved
  63.4% → 60.9% by telling them apart, which is the direction honesty went.
- **Quoted grants and ability words produced wrong parses** — Sedge Sliver read
  as its own pump; Enrage swallowed its trigger into a keyword parameter.
  Smells 4.83% → 2.11% across 60k effects.
- **`X` amounts parsed as −1** — "You gain X life" as gain_life(−1), endorsed
  by a test whose docstring forbade it. Amounts are now an int or the original
  token.
- **Keyword lines with semicolons parsed at 0%** ("Flying; swampwalk").
- **The changelog you are reading was 21 commits behind** its own repo.

### Changed

- Coverage reporting separates `text unread` from `vanilla`, and prints share
  of readable alongside share of all.

## [0.1.0] — 2026-08-11

Everything below existed before the repo was ever committed. `v0.1.0` is the
baseline tag: the work brought under version control and verified green, not a
plan-build-test-review cycle that just completed. 193 tests pass at this commit.

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
