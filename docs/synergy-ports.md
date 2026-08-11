# Synergy ports — where hyperedges come from

*2026-08-11. Implements search-problem.md §5.1: typed provide/require interfaces
over the parsed effect verbs. Census in `examples/synergy_census.py`.*

## The idea

A card is a node with **ports**: things it provides and things it requires,
read mechanically off its parsed effects, keywords, ability costs and trigger
conditions. A **hyperedge is a minimal set of cards that closes a port chain** —
every requirement met by a provision inside the set.

The chain form is what makes edges k-ary rather than pairwise. The canonical
example is the aristocrats package:

    token producer          provides  bodies
    sacrifice outlet        requires  bodies   →  provides  death_events
    death-trigger payoff    requires  death_events

No pair of the three does anything; the triple closes. A pairwise graph
structurally cannot say this — which is the whole argument of §3(a).

## Port taxonomy v0

| Port | Provided by (evidence) | Required by (evidence) |
|---|---|---|
| `bodies` | `create_token` | sacrifice outlets: `sacrifice` effect on own permanents, or an ability *cost* containing "Sacrifice" |
| `death_events` | sacrifice outlets (conversion: bodies → death_events) | triggers matching "dies" / "put into a graveyard from the battlefield" |
| `counters` | `put_counters` with a `+1/+1`-style kind | `proliferate`; triggers on counters being placed |
| `graveyard` | `mill`, `discard`, self-sacrifice | `return_from_graveyard`; keywords flashback, escape, unearth, embalm, eternalize, scavenge, delve |
| `life_events` | `gain_life` | triggers matching "gain life" |
| `mana` | `add_mana` beyond land base | spells with cmc ≥ 6 |

Roles are per-card, not exclusive: a card can provide and require on the same
port (Grave Pact sacrifices *and* triggers), and conversion cards are one node
with a requires-side and a provides-side — that is what lets chains form.

## What the weights are, eventually

v0 counts structure only: a port matched is a port matched. Weighting a
hyperedge — how *much* the package is worth — is an evaluator question
(simulate with and without the package, CRN-paired), not a parsing question,
and it waits for an objective that can see synergy at all. Goldfish consistency
cannot; that is the composition-variance result's caveat working as designed.

## Known limits, so nobody discovers them later

- **Recall is bounded by the parser**: 65.6% of cards fully parse, and a port
  on an unparsed clause does not exist here. Bounded and known beats implicit.
- **Triggers are matched as text.** The trigger strings come out of the parser
  whole; port detection regexes them. Wrong side of the every-clause-a-verb
  rule, accepted for v0 because triggers are short and highly templated.
- **`sacrifice` the effect vs the cost matter differently** — an outlet you
  control (cost, repeatable) is a stronger consumer than a one-shot edict
  effect. v0 records both as consumers and tags which; weights can care later.
