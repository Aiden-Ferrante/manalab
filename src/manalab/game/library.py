"""Turning a decklist into something you can shuffle and draw from."""

from __future__ import annotations

import random
from typing import Mapping, Sequence

from manalab.cards.model import Card, Decklist


def resolve(deck: Decklist, cards: Mapping[str, Card]) -> tuple[Card, ...]:
    """Expand a decklist into one Card per physical card.

    Card objects are frozen and shared across copies — the sim never mutates a
    Card, only the per-game bookkeeping around it.
    """
    missing = set(deck.counts) - set(cards)
    if missing:
        raise KeyError(f"no card data for: {sorted(missing)}")
    return tuple(cards[cid] for cid in deck.expand())


def shuffle(library: Sequence[Card], rng: random.Random) -> list[Card]:
    """A fresh shuffled copy. Never shuffles in place — the resolved deck is reused
    across every game in a run, which is what makes common random numbers cheap."""
    out = list(library)
    rng.shuffle(out)
    return out
