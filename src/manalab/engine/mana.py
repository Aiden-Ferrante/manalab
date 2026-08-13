"""Paying for things by tapping permanents.

The matching solver lives in `manalab.cards.payment`; this module is the part
that knows about a battlefield — which permanents are available, and which ones
actually get tapped.

**Known approximation, and it is a real one:** every mana source is treated as
producing exactly one mana. Sol Ring, Black Lotus, and every land that taps for
two are undercounted. `unmodeled_sources` reports them by name rather than
letting the engine quietly play a weaker game than the cards allow. Fixing this
properly is the job of the effect-verb layer, which will say how much mana a
permanent actually makes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from manalab.cards.mana import ManaCost
from manalab.cards.payment import Source, assign
from manalab.engine.objects import GameObject
from manalab.engine.state import GameState

MULTI_MANA = re.compile(r"add (?:\{[^}]+\}\s*){2,}", re.I)


@dataclass(frozen=True)
class Payment:
    """A chosen way to pay a cost: which permanents to tap."""

    tapped: tuple[int, ...]

    def __len__(self) -> int:
        return len(self.tapped)


def sources(state: GameState, player: int) -> list[GameObject]:
    """Permanents that could be tapped for mana right now.

    Summoning sickness applies to creature sources (mana dorks) but not to
    artifacts or lands, which is `GameObject.can_tap`'s job.
    """
    return [
        obj
        for obj in state.battlefield(player)
        if obj.card.taps_for_mana and obj.can_tap
    ]


def plan(state: GameState, player: int, cost: ManaCost) -> Payment | None:
    """Work out which permanents to tap, without tapping them."""
    available = sources(state, player)
    colors: list[Source] = [obj.card.produces for obj in available]

    chosen = assign(cost, colors)
    if chosen is None:
        return None
    return Payment(tuple(available[i].id for i in chosen))


def can_pay(state: GameState, player: int, cost: ManaCost) -> bool:
    return plan(state, player, cost) is not None


def pay(state: GameState, player: int, cost: ManaCost) -> Payment:
    """Tap permanents to pay `cost`. Raises if it cannot be paid."""
    payment = plan(state, player, cost)
    if payment is None:
        raise ValueError(f"cannot pay {cost} with {len(sources(state, player))} sources")

    for obj_id in payment.tapped:
        state.objects[obj_id].tapped = True
    return payment


def available_mana(state: GameState, player: int) -> int:
    """Count of untapped sources. Not the amount of mana available — see the
    module docstring — which is why this is deliberately not called that."""
    return len(sources(state, player))


def unmodeled_sources(state: GameState, player: int | None = None) -> dict[str, str]:
    """Permanents whose mana production the engine gets wrong, by name."""
    out: dict[str, str] = {}
    for obj in state.battlefield(player):
        if obj.card.taps_for_mana and MULTI_MANA.search(obj.card.oracle_text):
            out[obj.card.name] = "produces more than one mana; counted as one"
    return out
