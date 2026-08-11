# ADR 0001: Build the simulator, adopt the data

Date: 2026-08-08
Status: accepted

## Context

manalab began as "a Magic simulator for testing strategy theories". The standing
fleet preference is to adopt mature tools rather than build custom ones. A survey
of the existing landscape was run before writing any code.

**Rules engines that exist and are alive:** Forge (2.6k★, GPL-3.0, ~18,500 cards,
a first-class headless `sim` batch mode), XMage (2.3k★, MIT, 31k cards, but built
as a play platform with no batch CLI), and Argentum Engine (55★, Kotlin, a
purpose-built Gymnasium wrapper — the best research substrate, and far too young
to depend on).

**Python rules engines:** a graveyard. The largest, `open-mtg` (153★), was last
touched in 2019. Every other candidate is an abandoned hobby repo. There is no
maintained Python MTG engine and no PettingZoo or OpenSpiel environment.

**Goldfish simulators:** also nothing. Every candidate is a single-author script
with no API, several archived since 2016.

**Data:** excellent, free, keyless. Scryfall bulk exports, MTGJSON, and 17Lands'
public datasets (CC BY 4.0, millions of real games).

## Decision

**Build the simulator. Adopt the data.**

This inverts the fleet's buy-before-build default, and the inversion is justified
by the survey rather than by preference: there is genuinely nothing to buy at the
simulation layer.

The deeper reason is about *objectives*, not availability. Forge is real and
does what you would want mechanically, but its own wiki says the AI "is not
'trained'... can be easy to overcome knowing its weaknesses." It plays control
badly and combo very badly. So "win rate against Forge's AI" is a **confidently
wrong** objective: it measures decks against a mediocre heuristic player with
great precision. A narrow objective you can defend beats a precise measurement of
the wrong quantity, and that is the worst failure mode in optimisation because it
is invisible from inside the loop.

## Consequences

- The simulator is *ours*, and therefore disposable and replaceable — which is
  what ADR 0002's seam is for.
- Card data is a build artifact, never committed; `manalab fetch && manalab build`
  reconstructs it. Attribution obligations are recorded in `ATTRIBUTION.md`.
- A Forge-backed evaluator remains available later as a second implementation
  behind the same protocol, with its AI treated as a weak baseline opponent
  rather than as ground truth.
- 17Lands remains the only real ground truth available, which is why validating
  against it is a milestone rather than an afterthought.
