"""Card, effect, and decklist types. The vocabulary every other layer speaks."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from functools import cached_property
from typing import Iterable, Mapping, Sequence

from manalab.cards.mana import ManaCost, parse_cost, parse_produced
from manalab.cards.types import TypeLine, parse_type_line


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


@dataclass(frozen=True)
class Ability:
    """One ability, with the *shape* that tells you when it happens.

    An `Effect` says what a card does. It cannot say when, and "draw a card" and
    "when this creature enters, draw a card" are different cards. The parser has
    always known the difference — it records `kind` and the trigger condition —
    but `Parsed.effects` flattened every ability into one tuple and `Card` only
    ever carried that tuple, so by the time the engine saw a card the difference
    was gone. Everything downstream then had to assume "spell", which is why
    permanents resolved to the battlefield doing nothing at all.

    `kind` is one of `spell`, `activated`, `triggered`, `static`, `keyword`.
    """

    kind: str
    text: str = ""
    effects: tuple[Effect, ...] = ()
    unparsed: tuple[str, ...] = ()
    cost: str = ""
    trigger: str = ""
    """The condition, as printed: "this creature enters", "CARDNAME dies"."""
    matched_clauses: int = 0
    """Clauses that produced at least one effect. Kept apart from
    `len(effects)` because one clause can match several patterns, and counting
    effects put 5,223 phantom matches into the coverage numerator AND
    denominator — the more verbs a clause carried, the better it looked."""

    @property
    def fully_parsed(self) -> bool:
        return not self.unparsed


@dataclass(frozen=True)
class Face:
    """One printed side. Most cards have exactly one.

    Parsed separately from its siblings, and under its *own* name: `normalise`
    substitutes the card name with `~`, and the text of Fire says "Fire deals 2
    damage" — passing the joined "Fire // Ice" would never match. Per-face parsing
    is a correctness requirement, not tidiness.
    """

    index: int
    name: str
    oracle_text: str = ""
    mana_cost: str = ""
    type_line: str = ""
    power: str = ""
    toughness: str = ""
    loyalty: str = ""

    @cached_property
    def types(self) -> TypeLine:
        """Supertypes, card types and subtypes, split from `type_line`.

        Per face because the halves differ: `Brazen Borrower` is a Creature on face
        0 and an Instant — Adventure on face 1, and the joined top-level line says
        both at once, which is true of the card and of neither side.
        """
        return parse_type_line(self.type_line)


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
    abilities: tuple[Ability, ...] = ()
    """The same effects, still attached to the ability that owns them.

    `effects` is the flattened view every existing caller uses; this is the one
    that can answer "is that draw a spell or an enters-the-battlefield trigger?"
    Both are carried because flattening is lossy and nothing should have to
    re-parse a card to recover what the parser already knew."""
    unparsed: tuple[str, ...] = ()
    """Clauses the parser could not match to a verb.

    Carried on the card rather than thrown away at parse time, because the
    engine's own honesty check needs it: `fidelity` asked `resolve` which verbs
    were unsupported, and `resolve` can only see the effects that *did* parse.
    Text the parser never matched was therefore invisible to the one mechanism
    whose job is to notice it, and 90 of 819 cards in the searchable pool were
    called faithful while carrying clauses nobody had read."""
    power: str = ""
    toughness: str = ""
    """Printed as strings: Magic has `*`, `1+*` and `?`, none of which are ints."""
    loyalty: str = ""
    keywords: frozenset[str] = frozenset()
    colors: frozenset[str] = frozenset()
    color_identity: frozenset[str] = frozenset()
    edhrec_rank: int | None = None
    """Scryfall's EDHREC popularity rank — lower is more played. Crowd-distilled
    card quality for exactly this format, and the measured answer to why the
    first pipeline's decks sat below fair share: a synergy score knows which
    cards connect, not which are any good. None for cards EDHREC has no data
    on, which is itself a signal."""
    faces: tuple[Face, ...] = ()
    """Every printed side, in printed order. Always at least one once loaded from
    the store — a single-faced card gets a synthesised face 0 — so nothing reading
    faces has to branch on layout."""

    @property
    def card_types(self) -> frozenset[str]:
        """Every card type on any face — the grouping key for optimization.

        Union on purpose: a deckbuilder counting creatures should count Brazen
        Borrower, and one counting instants should count it too. Falls back to
        parsing the joined type_line for cards built without faces.
        """
        if self.faces:
            return frozenset(t for f in self.faces for t in f.types.card_types)
        return frozenset(parse_type_line(self.type_line).card_types)

    def is_type(self, card_type: str) -> bool:
        return card_type.lower() in self.card_types

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
        edhrec_rank=(int(row["edhrec_rank"])
                     if row.get("edhrec_rank") is not None else None),
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
