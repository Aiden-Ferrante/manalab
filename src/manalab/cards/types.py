"""Type lines, split into supertypes, card types and subtypes.

    Legendary Artifact Creature — Golem
    ^^^^^^^^^ ^^^^^^^^^^^^^^^^^   ^^^^^
    supertype    card types      subtype

The governing rule is the one `effects.py` already sets for itself: every word is
either recognised or recorded as unknown. A type line that half-parses silently is
worse than one that refuses, because the engine's behaviour turns on card type —
"is this a creature" decides whether it can attack.

The corpus makes that rule earn its keep. Alongside the fifteen card types there
are joke sets (`Eaturecray`, `Universewalker`, `pLAnE`, `Phenome-nom`), pre-6th
edition wording (`Summon Dragon`), and objects that are not cards at all but appear
in the same field (`Emblem`, `Stickers`). None of those should quietly become a
subtype, which is what splitting on the dash and trusting the halves would do.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: The five supertypes, plus two that only exist in Un-sets.
SUPERTYPES = frozenset({
    "basic", "legendary", "ongoing", "snow", "world",
    # Un-sets and supplemental products: "Hero Artifact — Equipment" (Battle the
    # Horde), "Elite Creature — Head", "Host Creature — Bird".
    "elite", "host", "hero",
})

#: The fifteen card types from the comprehensive rules.
CARD_TYPES = frozenset({
    "artifact", "battle", "conspiracy", "creature", "dungeon", "enchantment",
    "instant", "kindred", "land", "phenomenon", "plane", "planeswalker",
    "scheme", "sorcery", "vanguard",
})

#: Objects that carry a type line without being cards. Kept distinct from
#: CARD_TYPES so "is this one of the fifteen" stays an answerable question.
NON_CARD_TYPES = frozenset({"emblem", "token", "stickers", "card", "event", "boss"})

#: Renames and pre-modern wording. `Tribal` became `Kindred` in 2024; `Summon`
#: is how creatures were printed before Sixth Edition.
ALIASES = {"tribal": "kindred", "summon": "creature"}

# Scryfall uses an em-dash; four lines in the corpus use a hyphen, and at least one
# joke card ("Phenome-nom") contains a hyphen that is *not* a separator — so the
# split requires surrounding whitespace.
_SPLIT = re.compile(r"\s+[—–-]\s+")


@dataclass(frozen=True)
class TypeLine:
    """A parsed type line. `unknown` is never dropped."""

    supertypes: tuple[str, ...] = ()
    card_types: tuple[str, ...] = ()
    subtypes: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()
    raw: str = ""

    @property
    def understood(self) -> bool:
        """Whether every word before the dash was recognised."""
        return not self.unknown

    def is_a(self, card_type: str) -> bool:
        return card_type.lower() in self.card_types

    @property
    def is_permanent(self) -> bool:
        """Permanents stay on the battlefield. Instants and sorceries do not, and
        neither do the objects that are not cards."""
        return bool(self.card_types) and not (
            {"instant", "sorcery"} & set(self.card_types)) and not (
            set(self.card_types) & NON_CARD_TYPES)


def parse_type_line(text: str) -> TypeLine:
    """Split a type line. Unrecognised words before the dash become `unknown`.

    Subtypes are taken as written: there are thousands of them, they change every
    set, and validating against a list would mean maintaining that list forever for
    no gain — an unknown *subtype* costs nothing, while an unknown *card type* means
    the engine cannot tell what the object is.
    """
    raw = (text or "").strip()
    if not raw:
        return TypeLine()

    parts = _SPLIT.split(raw, maxsplit=1)
    head, tail = parts[0], (parts[1] if len(parts) > 1 else "")
    supers: list[str] = []
    types: list[str] = []
    unknown: list[str] = []

    for word in head.split():
        key = ALIASES.get(word.lower(), word.lower())
        if key in SUPERTYPES:
            supers.append(key)
        elif key in CARD_TYPES or key in NON_CARD_TYPES:
            types.append(key)
        else:
            unknown.append(word)

    subs = list(tail.split()) if tail else []

    # Pre-Sixth-Edition wording puts the subtype straight after the type with no
    # dash: "Summon Goblin", "Summon Legend". Both forms exist in the corpus —
    # "Summon — Dinosaur" is dashed — so this only fires on the undashed one, where
    # the trailing words are subtypes rather than anything unrecognised.
    if not tail and unknown and "summon" in {w.lower() for w in head.split()}:
        subs, unknown = unknown, []

    return TypeLine(supertypes=tuple(supers), card_types=tuple(types),
                    subtypes=tuple(subs), unknown=tuple(unknown), raw=raw)
