"""Constructed formats: which cards are legal, and how a deck may be built.

Until now "the format" was the string `"modern"` threaded through `mono_color`,
and the construction rules were constants scattered across three modules — 60 in
`pool.partition`, a four-copy `default_max` on `CandidatePool` whose docstring
already said "1 in singleton" with nothing ever supplying it, and a basic-land
exemption written out as a set literal in two places. Nothing could express
Commander at all, because nobody owned "100 cards, one copy each, 40 life".

A `Format` is that owner. It answers four questions and nothing else:

    which cards may I play        -> legal_names(store)
    how many of each              -> copies_for(status)
    how many total                -> deck_size
    what life do we start at      -> starting_life

`starting_life` is carried here rather than in the engine deliberately. It is a
game constant, and `cards` interprets nothing about it — but Commander is *one*
concept, and splitting "100 cards, singleton" from "40 life" across two layers
would mean two places to edit and one of them being forgotten. The engine still
takes a plain `int`; `evaluate` reads it off the format and passes it down, so
no dependency points the wrong way.

Deck size is treated as **exact**, not as a minimum. Real constructed says "60 or
more", but a search over a fixed-length integer vector needs one number, and
every deck this project builds is exactly at the floor anyway. Formats where that
is wrong would need a different pool representation, not a different constant.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Mapping

from manalab.cards.model import CandidatePool, Card, Decklist

BASIC_LANDS = frozenset({"Plains", "Island", "Swamp", "Mountain", "Forest",
                         "Wastes", "Snow-Covered Plains", "Snow-Covered Island",
                         "Snow-Covered Swamp", "Snow-Covered Mountain",
                         "Snow-Covered Forest"})
"""Exempt from the copy limit in every format (CR 105.1a / 903.5b).

Snow basics are included because they are basic lands; whether a format allows
them is a legality question, answered by the store, not a copy-limit one."""


@dataclass(frozen=True)
class Format:
    name: str
    legality_key: str
    """The Scryfall `legalities` field this format reads."""

    deck_size: int = 60
    max_copies: int = 4
    starting_life: int = 20
    unlimited: frozenset[str] = BASIC_LANDS

    @property
    def singleton(self) -> bool:
        return self.max_copies == 1

    def copies_for(self, name: str, status: str = "legal") -> int:
        """How many of `name` this format allows.

        Three cases, in order: a basic land is capped only by the deck size; a
        *restricted* card is capped at one however many the format otherwise
        allows (this is the whole of Vintage's ban list); everything else gets
        the format's limit.
        """
        if name in self.unlimited:
            return self.deck_size
        if status == "restricted":
            return 1
        return self.max_copies

    def legal_names(self, store) -> dict[str, str]:
        """`{card name: 'legal' | 'restricted'}` for this format.

        Restricted is kept rather than flattened to a boolean, because it is the
        difference between "you may play four" and "you may play one" — and a
        Vintage pool that dropped restricted cards would be missing Ancestral
        Recall, Black Lotus and the rest of the format's defining cards.
        """
        return store.legality_in(self.legality_key)

    def violations(self, deck: Decklist, legal: Mapping[str, str]) -> list[str]:
        """Every way `deck` is not a legal deck in this format. Empty is legal.

        Takes the legality map rather than a store so it can be called in a loop
        without a query per deck, and so a caller can check a deck against a pool
        it has already built.
        """
        problems: list[str] = []

        if deck.size != self.deck_size:
            problems.append(
                f"deck has {deck.size} cards, {self.name} wants {self.deck_size}")

        for name, count in sorted(deck.counts.items()):
            status = legal.get(name)
            if status is None:
                problems.append(f"{name} is not legal in {self.name}")
                continue
            allowed = self.copies_for(name, status)
            if count > allowed:
                why = " (restricted)" if status == "restricted" else ""
                problems.append(
                    f"{count} copies of {name}{why}, {self.name} allows {allowed}")
        return problems

    def is_legal(self, deck: Decklist, legal: Mapping[str, str]) -> bool:
        return not self.violations(deck, legal)

    def candidate_pool(self, names, legal: Mapping[str, str]) -> CandidatePool:
        """A search axis over `names`, with this format's limits applied."""
        names = tuple(names)
        return CandidatePool(
            card_ids=names,
            max_copies={n: self.copies_for(n, legal.get(n, "legal")) for n in names},
            deck_size=self.deck_size,
            default_max=self.max_copies,
        )


STANDARD = Format("Standard", "standard")
PIONEER = Format("Pioneer", "pioneer")
MODERN = Format("Modern", "modern")
LEGACY = Format("Legacy", "legacy")
VINTAGE = Format("Vintage", "vintage")
PAUPER = Format("Pauper", "pauper")
COMMANDER = Format("Commander", "commander",
                   deck_size=100, max_copies=1, starting_life=40)
"""Singleton, 100 cards, 40 life. The commander itself is not modelled: it is a
zone this engine does not have, and pretending otherwise would make every
Commander deck 99 cards plus a card that never gets cast."""

ALL = (STANDARD, PIONEER, MODERN, LEGACY, VINTAGE, PAUPER, COMMANDER)
_BY_NAME = {f.name.lower(): f for f in ALL} | {f.legality_key: f for f in ALL}


def by_name(name: str) -> Format:
    """Look a format up by name or legality key. Raises on an unknown one.

    Deliberately strict: a typo'd format that silently fell back to Modern would
    produce a pool nobody asked for and a result nobody could reproduce.
    """
    try:
        return _BY_NAME[name.strip().lower()]
    except KeyError:
        raise KeyError(
            f"unknown format {name!r}; known: {', '.join(sorted(f.name for f in ALL))}"
        ) from None
