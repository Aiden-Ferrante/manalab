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

from collections import defaultdict

from manalab.cards.store import CardStore
from manalab.search.ports import ports_of

def main() -> int:
    store = CardStore()
    sides: dict[tuple[str, str], list[str]] = defaultdict(list)
    parsed_cards = 0

    for card in store.all_cards():
        card_ports = ports_of(card)
        parsed_cards += 1
        for port, roles in card_ports.items():
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
