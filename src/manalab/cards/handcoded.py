"""Cards implemented by name, because their text is theirs alone.

The parser handles families; some staples ARE the family. Nykthos's devotion
mana is one card's mechanic — a pattern for it would have exactly one match —
so it is written by hand: the registry supplies the parsed abilities, the
engine implements the verbs, and a test drives each entry against the real
store. Forge maintains 33,664 of these; this registry holds the handful worth
that treatment here, and every entry must earn its test.

Blessed whole by `fidelity`: an entry's contract is "implemented by hand,
verified by test", so the standard text checks are skipped for it. That makes
adding an entry a *promise*, which is why the registry is small on purpose.
"""

from __future__ import annotations

from manalab.cards.model import Ability, Effect

HANDCODED: dict[str, tuple[Ability, ...]] = {
    "Nykthos, Shrine to Nyx": (
        Ability(kind="activated", text="{T}: Add {C}.", cost="{T}",
                effects=(Effect("add_mana", (("mana", "{C}"),)),)),
        Ability(kind="activated",
                text="{2}, {T}: Choose a color. Add an amount of mana of that "
                     "color equal to your devotion to that color.",
                cost="{2}, {T}",
                effects=(Effect("devotion_mana", ()),)),
    ),
}

NAMES = frozenset(HANDCODED)
