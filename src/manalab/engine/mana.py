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
from dataclasses import dataclass, field, replace

from manalab.cards.mana import ManaCost
from manalab.cards.payment import Source, assign
from manalab.engine.objects import GameObject
from manalab.engine.state import GameState

MULTI_MANA = re.compile(r"add (?:\{[^}]+\}\s*){2,}", re.I)


@dataclass(frozen=True)
class Payment:
    """A chosen way to pay a cost: floating mana spent, and permanents tapped."""

    tapped: tuple[int, ...]
    from_pool: dict[str, int] = field(default_factory=dict)
    """Floating mana used, by colour. Spending this first is what makes a ritual
    worth casting — otherwise its mana would have nowhere to go."""

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


def spend_pool(pool: dict[str, int], cost: ManaCost) -> tuple[dict[str, int], ManaCost]:
    """What floating mana covers, and the cost left to pay by tapping.

    Coloured pips are matched first and generic last, because spending a green
    mana on a generic pip when a {G} is still unpaid is how a payable cost turns
    unpayable. Returns the spend and the residual, mutating nothing.
    """
    left = dict(pool)
    spent: dict[str, int] = {}
    unmatched: list[frozenset[str]] = []

    for symbol in cost.symbols:
        match = next((c for c in sorted(symbol) if left.get(c, 0) > 0), None)
        if match is None:
            unmatched.append(symbol)
            continue
        left[match] -= 1
        spent[match] = spent.get(match, 0) + 1

    generic = cost.generic
    for color in sorted(left):
        while generic and left[color] > 0:
            left[color] -= 1
            spent[color] = spent.get(color, 0) + 1
            generic -= 1

    return spent, replace(cost, generic=generic, symbols=tuple(unmatched))


def plan(state: GameState, player: int, cost: ManaCost) -> Payment | None:
    """Work out which permanents to tap, without tapping them."""
    pool = state.players[player].mana_pool
    from_pool, remaining = spend_pool(pool, cost) if pool else ({}, cost)

    available = sources(state, player)
    colors: list[Source] = [obj.card.produces for obj in available]

    chosen = assign(remaining, colors)
    if chosen is None:
        return None
    return Payment(tuple(available[i].id for i in chosen), from_pool)


def can_pay(state: GameState, player: int, cost: ManaCost) -> bool:
    return plan(state, player, cost) is not None


def pay(state: GameState, player: int, cost: ManaCost) -> Payment:
    """Spend floating mana and tap permanents to pay `cost`."""
    payment = plan(state, player, cost)
    if payment is None:
        raise ValueError(f"cannot pay {cost} with {len(sources(state, player))} sources")

    pool = state.players[player].mana_pool
    for color, count in payment.from_pool.items():
        pool[color] -= count
        if pool[color] <= 0:
            del pool[color]
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
