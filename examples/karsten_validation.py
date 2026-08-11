"""Validate the simulator against Frank Karsten's colored-source tables.

Karsten's numbers are the field standard for "how many sources of a color do I
need", derived analytically and independently of this tool. Reproducing them is
the strongest external check available on the mana model — it exercises card
parsing, the mulligan rule, land sequencing and the payment solver at once.

Run it after touching anything in `manalab.game`:

    python examples/karsten_validation.py

Expected: ~14 sources for 90% on a turn-1 single pip, and ~12 for 90% on a
turn-3 single pip *conditional on having three lands*. The conditioning matters
— see below.

This script found two real bugs when it was first written. Land sequencing
ignored what was in hand, so a deck holding a Mountain, a Plains and a {R}
one-drop played the Plains half the time. And fetchlands were parsed as
producing no mana at all, since that is literally what Scryfall reports.
"""

from __future__ import annotations

from manalab.cards.mana import parse_cost
from manalab.cards.model import Card, Decklist
from manalab.game import goldfish
from manalab.game.library import resolve

GAMES = 40_000
LANDS = 24


def land(name: str, color: str) -> Card:
    return Card(name, name, parse_cost(None), "Land",
                produces=frozenset(color), taps_for_mana=True)


CARDS = {
    c.name: c
    for c in (
        land("Mountain", "R"),
        land("Plains", "W"),
        Card("b", "Bolt", parse_cost("{R}"), "Instant"),
        Card("d", "Drake", parse_cost("{2}{R}"), "Creature"),
        Card("f", "Filler", parse_cost("{5}"), "Sorcery"),
    )
}


def main() -> None:
    print(f"{LANDS} lands total, N of them producing {{R}}. {GAMES:,} games per row.")
    print("Conditioned on holding the spell in the opening hand.\n")
    print(f"{'R sources':>10} {'1-drop t1':>11} {'3-drop t3':>11} {'3-drop t3':>11}")
    print(f"{'':>10} {'':>11} {'raw':>11} {'| 3 lands':>11}")

    for n in range(9, 21):
        deck = Decklist(
            {
                "Mountain": n,
                "Plains": LANDS - n,
                "Bolt": 4,
                "Drake": 4,
                "Filler": 60 - LANDS - 8,
            }
        )
        library = resolve(deck, CARDS)

        had1 = ok1 = had3 = ok3 = lands3 = 0
        for seed in range(GAMES):
            game = goldfish.play(library, seed=seed, turns=3)
            if "Bolt" in game.opening_hand:
                had1 += 1
                ok1 += game.castable_by("Bolt", 1)
            if "Drake" in game.opening_hand:
                had3 += 1
                # The raw turn-3 number is capped by whether you even hit three
                # land drops, which is a land-count question, not a color one.
                # Karsten reports the color question, so condition on the lands.
                if game.mana_available[2] >= 3:
                    lands3 += 1
                    ok3 += game.castable_by("Drake", 3)

        mark = ""
        if n == 14:
            mark = "  <- Karsten: 14 for t1"
        elif n == 12:
            mark = "  <- Karsten: 12 for t3"

        print(
            f"{n:>10} {ok1 / had1:>11.3f} "
            f"{ok3 / had3:>11.3f} {ok3 / lands3:>11.3f}{mark}"
        )


if __name__ == "__main__":
    main()
