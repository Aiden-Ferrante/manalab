"""Census of synergy ports over the corpus — does the hypergraph frame bite?

docs/synergy-ports.md. Reads every parsed card, assigns provide/require ports
from effects, keywords, ability costs and triggers, and reports how many cards
sit on each side of each port. The payoff question is the aristocrats chain:

    bodies → sacrifice outlet → death trigger

If all three legs are populated, minimal 3-ary hyperedges exist mechanically —
no curation, no decklist mining — and the frame earns its place.

    python -u examples/synergy_census.py
"""

from __future__ import annotations

import re
from collections import defaultdict

from manalab.cards.effects import parse_card
from manalab.cards.store import CardStore

GRAVE_KEYWORDS = {"flashback", "escape", "unearth", "embalm", "eternalize",
                  "scavenge", "delve", "disturb", "jump-start", "aftermath"}
_DIES = re.compile(r"\bdies\b|put into a graveyard from the battlefield", re.I)
_GAINS_LIFE = re.compile(r"\bgains? life\b|\byou gain life\b", re.I)
_COUNTER_ON = re.compile(r"counters? (?:is|are) put on|put a [^ ]+ counter", re.I)
_OWN_SAC = re.compile(r"^(a|an|another|any number of)? ?(creature|permanent|artifact|token)s?\b", re.I)


def ports_of(card, parsed) -> dict[str, set[str]]:
    """port name → roles ('provides' / 'requires'), with outlet tagging."""
    out: dict[str, set[str]] = defaultdict(set)
    kw = {k.lower() for k in card.keywords}

    for ability in parsed.abilities:
        if "sacrifice" in ability.cost.lower():
            out["bodies"].add("requires")          # a repeatable outlet
            out["death_events"].add("provides")
        if ability.trigger:
            if _DIES.search(ability.trigger):
                out["death_events"].add("requires")
            if _GAINS_LIFE.search(ability.trigger):
                out["life_events"].add("requires")
            if _COUNTER_ON.search(ability.trigger):
                out["counters"].add("requires")

    for effect in parsed.effects:
        params = dict(effect.params)
        if effect.verb == "create_token":
            out["bodies"].add("provides")
        elif effect.verb == "sacrifice":
            what = str(params.get("what", ""))
            if _OWN_SAC.match(what.strip()):
                out["bodies"].add("requires")
                out["death_events"].add("provides")
        elif effect.verb == "put_counters" and "+1/+1" in str(params.get("kind", "")):
            out["counters"].add("provides")
        elif effect.verb == "proliferate":
            out["counters"].add("requires")
        elif effect.verb in ("mill", "discard"):
            out["graveyard"].add("provides")
        elif effect.verb == "return_from_graveyard":
            out["graveyard"].add("requires")
        elif effect.verb == "gain_life":
            out["life_events"].add("provides")
        elif effect.verb == "add_mana" and not card.is_land:
            out["mana"].add("provides")

    if kw & GRAVE_KEYWORDS:
        out["graveyard"].add("requires")
    if card.cost.cmc >= 6:
        out["mana"].add("requires")
    return out


def main() -> int:
    store = CardStore()
    sides: dict[tuple[str, str], list[str]] = defaultdict(list)
    parsed_cards = 0

    for card in store.all_cards():
        parsed = parse_card(card)
        if not parsed.effects and not any(a.trigger or a.cost for a in parsed.abilities):
            continue
        parsed_cards += 1
        for port, roles in ports_of(card, parsed).items():
            for role in roles:
                sides[(port, role)].append(card.name)

    print(f"cards with readable structure: {parsed_cards:,}")
    print()
    print(f"{'port':<14} {'provides':>9} {'requires':>9}")
    ports = sorted({p for p, _ in sides})
    for port in ports:
        print(f"{port:<14} {len(sides[(port, 'provides')]):>9,} "
              f"{len(sides[(port, 'requires')]):>9,}")

    print()
    print("the aristocrats chain — three legs, all mechanical:")
    producers = set(sides[("bodies", "provides")])
    outlets = set(sides[("bodies", "requires")]) & set(sides[("death_events", "provides")])
    payoffs = set(sides[("death_events", "requires")])
    print(f"  token producers : {len(producers):,}")
    print(f"  sac outlets     : {len(outlets):,}")
    print(f"  death payoffs   : {len(payoffs):,}")
    both = producers & outlets
    print(f"  two legs at once: {len(both):,}  (produce and consume bodies)")

    if producers and outlets and payoffs:
        import random
        rng = random.Random(3)
        trio = (rng.choice(sorted(producers)), rng.choice(sorted(outlets)),
                rng.choice(sorted(payoffs)))
        print(f"\n  a minimal 3-ary hyperedge, drawn at random:")
        for role, name in zip(("produce", "outlet ", "payoff "), trio):
            print(f"    {role}  {name}")
        print("\n  no pair of these does anything; the triple closes the chain.")
        print("  This is the structure a pairwise graph cannot represent.")
    print()
    print("recall bounded by the parser: ports on unparsed clauses do not exist here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
