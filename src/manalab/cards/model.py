"""Card, effect, and decklist types. The vocabulary every other layer speaks."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from manalab.cards.mana import ManaCost, parse_cost, parse_produced


@dataclass(frozen=True)
class Effect:
    """One unit of card behaviour, as data.

    Cards are never modeled as fixed fields ("a creature with power/toughness").
    They carry a tuple of these. The abstract sim implements a handful of verbs
    and reports the rest as unmodeled rather than silently ignoring them.

    Growing fidelity == implementing more verbs. See ARCHITECTURE.md.
    """

    verb: str
    params: tuple[tuple[str, str | int], ...] = ()

    def get(self, key: str, default: str | int | None = None) -> str | int | None:
        return dict(self.params).get(key, default)


FACED_LAYOUTS = frozenset({
    "transform", "adventure", "split", "modal_dfc", "flip", "prepare",
    "double_faced_token", "meld", "battle_class", "reversible_card",
})
"""Layouts whose text lives in `card_faces`. Measured over the 35,139 loaded cards:
transform 401, adventure 170, split 137, modal_dfc 100, prepare 55, flip 21 — every
one of them arrives with a blank top-level `oracle_text`."""


@dataclass(frozen=True)
class Card:
    """A card's printed characteristics. Never its state in a game.

    Frozen and shared: every copy of Lightning Bolt in a deck is the *same*
    `Card` object. Anything that varies between two copies on the battlefield —
    tapped, damage, counters, who controls it — belongs to the engine's
    `GameObject`, never here.
    """

    oracle_id: str
    name: str
    cost: ManaCost
    type_line: str
    layout: str = "normal"
    """Scryfall's layout. `normal` has one face; `transform`, `adventure`, `split`,
    `modal_dfc`, `flip` and `prepare` keep their text in `card_faces`, which is why
    a blank `oracle_text` on those means *unread*, not *vanilla*."""
    produces: frozenset[str] = frozenset()
    """Colors of mana this card can add. Empty for non-producers."""
    taps_for_mana: bool = False
    """Whether it produces mana at all, including colorless-only sources."""
    enters_tapped: bool = False
    oracle_text: str = ""
    effects: tuple[Effect, ...] = ()
    power: str = ""
    toughness: str = ""
    """Printed as strings: Magic has `*`, `1+*` and `?`, none of which are ints."""
    loyalty: str = ""
    keywords: frozenset[str] = frozenset()
    colors: frozenset[str] = frozenset()
    color_identity: frozenset[str] = frozenset()

    @property
    def has_faces(self) -> bool:
        """Whether this card's text lives on faces rather than at the top level."""
        return self.layout in FACED_LAYOUTS

    @property
    def is_land(self) -> bool:
        return "Land" in self.type_line

    @property
    def is_creature(self) -> bool:
        return "Creature" in self.type_line

    @property
    def is_permanent(self) -> bool:
        return any(
            t in self.type_line
            for t in ("Land", "Creature", "Artifact", "Enchantment", "Planeswalker", "Battle")
        )

    @property
    def cmc(self) -> int:
        return self.cost.cmc

    def has(self, keyword: str) -> bool:
        return keyword.lower() in {k.lower() for k in self.keywords}

    @property
    def base_power(self) -> int | None:
        """Printed power as an int, or None when it is a characteristic-defining `*`."""
        return _as_int(self.power)

    @property
    def base_toughness(self) -> int | None:
        return _as_int(self.toughness)


def _as_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


_ENTERS_TAPPED = re.compile(r"enters (?:the battlefield )?tapped", re.I)

# Lands whose tapped-ness is a choice or a condition the controller usually
# meets. Two distinct shapes:
#   checklands/fastlands  "...enters tapped unless you control two or fewer..."
#   shocklands            "...you may pay 2 life. If you don't, it enters tapped."
# Both are modeled as entering UNTAPPED, which is the optimistic read and the
# one a real player achieves most of the time. It is still a read: a deck whose
# result hinges on shocklands should be checked by hand.
_CONDITIONAL_TAPPED = re.compile(
    r"enters[^.]*tapped unless|you may pay[^.]*\.\s*if you don'?t", re.I
)

# "Search your library for a Mountain or Plains card, put it onto the battlefield"
_FETCH = re.compile(r"search your library for an? ([^,.]*?) card", re.I)
_FETCH_TAPPED = re.compile(r"onto the battlefield tapped", re.I)

BASIC_LAND_COLOR = {
    "plains": "W",
    "island": "U",
    "swamp": "B",
    "mountain": "R",
    "forest": "G",
}


def _fetched_colors(text: str) -> frozenset[str] | None:
    """Colors a fetchland can reach, or None if this isn't a fetchland.

    Scryfall gives fetchlands an empty `produced_mana` — correctly, since they
    tap for nothing. Modeling them that way makes them dead lands and badly
    understates every deck that plays them. Treating a fetch as a dual that
    produces whatever it can search for is far closer to the truth for
    consistency questions; it costs a life and can't be held up, neither of
    which this simulator models anyway.
    """
    match = _FETCH.search(text)
    if not match:
        return None
    phrase = match.group(1).lower()
    colors = {c for basic, c in BASIC_LAND_COLOR.items() if basic in phrase}
    return frozenset(colors) if colors else None


def card_from_scryfall(row: Mapping[str, object]) -> Card:
    """Build a Card from one Scryfall oracle-cards record."""
    text = str(row.get("oracle_text") or "")
    type_line = str(row.get("type_line") or "")
    produced = row.get("produced_mana")
    produced_list = list(produced) if isinstance(produced, (list, tuple)) else None

    enters_tapped = bool(
        _ENTERS_TAPPED.search(text) and not _CONDITIONAL_TAPPED.search(text)
    )

    produces = parse_produced(produced_list)
    taps_for_mana = bool(produced_list)

    if "Land" in type_line and not taps_for_mana:
        fetched = _fetched_colors(text)
        if fetched is not None:
            produces, taps_for_mana = fetched, True
            enters_tapped = bool(_FETCH_TAPPED.search(text))

    return Card(
        oracle_id=str(row.get("oracle_id") or row.get("id") or row.get("name")),
        name=str(row.get("name")),
        cost=parse_cost(row.get("mana_cost")),  # type: ignore[arg-type]
        type_line=type_line,
        layout=str(row.get("layout") or "normal"),
        produces=produces,
        taps_for_mana=taps_for_mana,
        enters_tapped=enters_tapped,
        oracle_text=text,
        effects=(),  # populated by the effect-verb layer; empty is honest for now
        power=str(row.get("power") or ""),
        toughness=str(row.get("toughness") or ""),
        loyalty=str(row.get("loyalty") or ""),
        keywords=_as_frozenset(row.get("keywords")),
        colors=_as_frozenset(row.get("colors")),
        color_identity=_as_frozenset(row.get("color_identity")),
    )


def _as_frozenset(value: object) -> frozenset[str]:
    if isinstance(value, (list, tuple)):
        return frozenset(str(v) for v in value)
    return frozenset()


@dataclass(frozen=True)
class Decklist:
    """A multiset of card ids. Deliberately not a list of Card objects.

    Search manipulates decklists constantly; keeping them as plain counts means
    the search layer never touches card data or the game model.
    """

    counts: Mapping[str, int]
    name: str = ""

    def __post_init__(self) -> None:
        if any(v < 0 for v in self.counts.values()):
            raise ValueError("negative card count")
        object.__setattr__(
            self, "counts", dict(sorted((k, v) for k, v in self.counts.items() if v))
        )

    @property
    def size(self) -> int:
        return sum(self.counts.values())

    def __len__(self) -> int:
        return self.size

    def expand(self) -> list[str]:
        """One entry per physical card. The thing you shuffle."""
        out: list[str] = []
        for cid, n in self.counts.items():
            out.extend([cid] * n)
        return out

    def with_change(self, card_id: str, delta: int) -> "Decklist":
        counts = dict(self.counts)
        counts[card_id] = max(0, counts.get(card_id, 0) + delta)
        return Decklist(counts, self.name)

    @classmethod
    def from_names(
        cls, entries: Iterable[tuple[str, int]], name: str = ""
    ) -> "Decklist":
        return cls(dict(Counter({k: v for k, v in entries})), name)


@dataclass(frozen=True)
class CandidatePool:
    """An ordered card pool, so search can treat a decklist as an integer vector.

    This is the entire interface search needs to a deck: a fixed axis order, a
    per-card maximum (4 in constructed, 1 in singleton), and a target size.
    """

    card_ids: tuple[str, ...]
    max_copies: Mapping[str, int] = field(default_factory=dict)
    deck_size: int = 60
    default_max: int = 4

    def limit(self, card_id: str) -> int:
        return self.max_copies.get(card_id, self.default_max)

    @property
    def upper_bounds(self) -> tuple[int, ...]:
        return tuple(self.limit(c) for c in self.card_ids)

    def to_vector(self, deck: Decklist) -> tuple[int, ...]:
        unknown = set(deck.counts) - set(self.card_ids)
        if unknown:
            raise KeyError(f"cards outside pool: {sorted(unknown)}")
        return tuple(deck.counts.get(c, 0) for c in self.card_ids)

    def from_vector(self, vector: Sequence[int], name: str = "") -> Decklist:
        if len(vector) != len(self.card_ids):
            raise ValueError(
                f"vector length {len(vector)} != pool size {len(self.card_ids)}"
            )
        return Decklist(dict(zip(self.card_ids, vector)), name)

    def is_legal(self, deck: Decklist) -> bool:
        if deck.size != self.deck_size:
            return False
        return all(n <= self.limit(c) for c, n in deck.counts.items())
