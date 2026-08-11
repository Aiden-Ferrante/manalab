"""London mulligan.

Draw seven, decide, and on a keep put `mulligans` cards on the bottom. Policies
are plain callables so a mulligan rule can itself become a search variable —
"what keep-range maximises turn-3 castability" is a first-class experiment here.
"""

from __future__ import annotations

import random
from typing import Callable, Protocol, Sequence

from manalab.cards.model import Card

HAND_SIZE = 7


class KeepPolicy(Protocol):
    def __call__(self, hand: Sequence[Card], mulligans: int) -> bool: ...


class BottomPolicy(Protocol):
    def __call__(self, hand: Sequence[Card], n: int) -> tuple[int, ...]:
        """Indices of the `n` cards to put on the bottom."""


def land_window_keep(low: int = 2, high: int = 5, free_after: int = 3) -> KeepPolicy:
    """Keep if the land count sits in a window that tightens as the hand shrinks.

    The default (2-5 lands) is the conventional heuristic, not a derived optimum.
    Deriving the optimum is exactly the kind of thing this tool is for.
    """

    def policy(hand: Sequence[Card], mulligans: int) -> bool:
        if mulligans >= free_after:
            return True
        lands = sum(1 for c in hand if c.is_land)
        # Each mulligan means bottoming a card, so tolerate one fewer land.
        return (low - 0) <= lands <= max(low, high - mulligans)

    return policy


def bottom_worst(hand: Sequence[Card], n: int) -> tuple[int, ...]:
    """Bottom excess lands beyond four, then the most expensive spells."""
    if n <= 0:
        return ()

    land_idx = [i for i, c in enumerate(hand) if c.is_land]
    spell_idx = [i for i, c in enumerate(hand) if not c.is_land]

    order: list[int] = []
    order.extend(land_idx[4:])  # surplus lands go first
    order.extend(sorted(spell_idx, key=lambda i: -hand[i].cmc))
    order.extend(i for i in land_idx[:4] if i not in order)

    return tuple(order[:n])


def mulligan(
    library: list[Card],
    rng: random.Random,
    *,
    keep: KeepPolicy | None = None,
    bottom: BottomPolicy | None = None,
    max_mulligans: int = 4,
) -> tuple[list[Card], list[Card], int]:
    """Resolve mulligans. Returns `(hand, remaining_library, mulligans_taken)`.

    `library` is consumed. The caller owns the shuffled copy.
    """
    keep = keep or land_window_keep()
    bottom = bottom or bottom_worst

    for mulls in range(max_mulligans + 1):
        hand = library[:HAND_SIZE]
        rest = library[HAND_SIZE:]

        if mulls == max_mulligans or keep(hand, mulls):
            if mulls:
                to_bottom = set(bottom(hand, mulls))
                kept = [c for i, c in enumerate(hand) if i not in to_bottom]
                rest = rest + [c for i, c in enumerate(hand) if i in to_bottom]
                hand = kept
            return hand, rest, mulls

        # London: whole hand back, reshuffle, draw seven again.
        library = list(library)
        rng.shuffle(library)

    raise AssertionError("unreachable")  # pragma: no cover
