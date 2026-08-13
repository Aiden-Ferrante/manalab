"""Assembling a card pool the engine can be trusted on.

Lives in `evaluate` rather than `cards` for a reason worth stating: deciding
which cards are safe to search over needs *both* the card data and the engine's
account of its own blind spots. `cards` may not import `engine`, so a pool
builder there would need a hand-copied list of implemented keywords — a second
source of truth that silently drifts the first time a keyword is added.

The split this produces is the honest one:

  * **faithful** — every word on the card is executed. Search over these and the
    resulting win rate means what it says.
  * **text** — the card is playable as a body, but some of its text is ignored.
    Kept and labelled rather than dropped, so it is visible what the engine is
    throwing away, and which verbs would unlock the most cards if implemented.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable, Mapping

from manalab.cards.model import Card, CandidatePool
from manalab.cards.store import CardStore
from manalab.engine import fidelity


@dataclass(frozen=True)
class Pool:
    """A searchable pool plus everything that was set aside, and why."""

    pool: CandidatePool
    cards: Mapping[str, Card]
    """Name -> Card for every card in `pool`, ready to hand to an evaluator."""

    text_tier: tuple[Card, ...] = ()
    """Playable, but with text the engine ignores. Not in `pool`."""

    reasons: Mapping[str, tuple[str, ...]] = None  # type: ignore[assignment]
    """Why each text-tier card was set aside."""

    def __post_init__(self) -> None:
        if self.reasons is None:
            object.__setattr__(self, "reasons", {})

    @property
    def size(self) -> int:
        return len(self.pool.card_ids)

    def why(self, card_name: str) -> tuple[str, ...]:
        return tuple(self.reasons.get(card_name, ()))

    def gaps(self) -> list[tuple[str, int]]:
        """Reasons for exclusion, commonest first — the implement-next list."""
        counts: dict[str, int] = {}
        for reasons in self.reasons.values():
            for reason in reasons:
                key = reason.split(":")[0]
                counts[key] = counts.get(key, 0) + 1
        return sorted(counts.items(), key=lambda kv: kv[1], reverse=True)


def mono_color(
    store: CardStore,
    color: str = "G",
    *,
    fmt: str = "modern",
    max_cmc: int = 7,
    include_lands: bool = True,
    deck_size: int = 60,
) -> Pool:
    """Every single-colour card of `color` that is legal in `fmt`.

    Colourless cards are excluded deliberately: they are legal in a mono-green
    deck but they are not a *green* deckbuilding decision, and letting them in
    turns "what is the best mono-green deck" into "what is the best colourless
    deck with a forest in it".
    """
    identity = json.dumps([color])
    rows = store._rows(  # noqa: SLF001 - the store exposes no typed filter yet
        """
        color_identity = ?
        AND json_extract_string(legalities, '$.' || ?) = 'legal'
        AND cmc <= ?
        """,
        [identity, fmt, max_cmc],
    )
    candidates = [store._build(row) for row in rows]  # noqa: SLF001

    if include_lands:
        basic = store.by_name({"G": "Forest", "R": "Mountain", "U": "Island",
                               "W": "Plains", "B": "Swamp"}[color])
        candidates.append(basic)

    return partition(candidates, deck_size=deck_size, unlimited={"Forest", "Mountain",
                                                                "Island", "Plains", "Swamp"})


def partition(
    candidates: Iterable[Card],
    *,
    deck_size: int = 60,
    unlimited: Iterable[str] = (),
) -> Pool:
    """Split cards into the faithful pool and the marked text tier."""
    unlimited = set(unlimited)
    faithful: list[Card] = []
    text: list[Card] = []
    reasons: dict[str, tuple[str, ...]] = {}

    for card in sorted(set(candidates), key=lambda c: (c.cmc, c.name)):
        report = fidelity.assess(card)
        if report.faithful:
            faithful.append(card)
        else:
            text.append(card)
            reasons[card.name] = report.reasons

    # A basic land is capped by the deck size, not by the four-copy rule.
    max_copies = {c.name: deck_size for c in faithful if c.name in unlimited}

    pool = CandidatePool(
        card_ids=tuple(c.name for c in faithful),
        max_copies=max_copies,
        deck_size=deck_size,
    )
    return Pool(
        pool=pool,
        cards={c.name: c for c in faithful},
        text_tier=tuple(text),
        reasons=reasons,
    )
