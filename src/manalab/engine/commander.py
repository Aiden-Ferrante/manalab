"""The three rules that make Commander a format rather than a deck size.

`cards.formats` already says a Commander deck is 100 singleton cards at 40 life.
None of that needs the engine. These three do, and without them a "Commander
game" is just a long game of one-ofs:

  * **The command zone** (CR 903.6). A commander starts there, is cast from
    there, and each cast after the first costs {2} more. That tax is what stops
    a deck simply recasting its commander every turn forever.
  * **Commander replacement** (CR 903.9). A commander that would go to a
    graveyard or exile may return to the command zone instead — so removal
    answers it for a turn, not for the game.
  * **Commander damage** (CR 903.10a). 21 damage from any single commander is a
    loss, however high the life total. It is the reason a 40-life format is not
    simply a 20-life format twice over.

Kept in its own module rather than threaded through `sba` and `mana` because it
is the only place any of it is true — nothing about a two-player constructed
game should have to know these rules exist.
"""

from __future__ import annotations

from dataclasses import replace

from typing import TYPE_CHECKING

from manalab.cards.mana import ManaCost
from manalab.engine.objects import GameObject
from manalab.engine.zones import Zone

if TYPE_CHECKING:  # `state` imports this module for the 903.9 replacement
    from manalab.engine.state import GameState

COMMANDER_DAMAGE_LOSS = 21
"""CR 903.10a. Twenty-one, not the life total — that is the whole point."""

TAX_PER_CAST = 2
"""CR 903.8. Generic, and it does not care what the commander costs."""


def tax_for(state: GameState, player: int) -> int:
    """Extra generic mana this player's next commander cast costs."""
    return TAX_PER_CAST * state.players[player].commander_casts


def cost_from_command_zone(state: GameState, obj: GameObject) -> ManaCost:
    """`obj`'s cost with the commander tax applied.

    The tax is generic, so it lands on the generic component and leaves the
    coloured pips alone — a commander does not become harder to *colour* the
    more often it is cast, only more expensive.
    """
    tax = tax_for(state, obj.controller)
    if not tax:
        return obj.card.cost
    cost = obj.card.cost
    return replace(cost, generic=cost.generic + tax)


def note_cast(state: GameState, player: int) -> None:
    """Record a commander cast, so the next one costs {2} more."""
    state.players[player].commander_casts += 1


def deal_commander_damage(state: GameState, victim: int, source: GameObject,
                          amount: int) -> None:
    """Track damage from one commander, by the commander it came from.

    Kept per source rather than as a total: twenty from one commander and twenty
    from another is not a loss, and folding them together would make it one.
    """
    if not source.is_commander or amount <= 0:
        return
    tally = state.players[victim].commander_damage
    tally[source.card.name] = tally.get(source.card.name, 0) + amount


def lethal_commander_damage(state: GameState, player: int) -> str | None:
    """The commander that has dealt this player 21, if any."""
    for name, dealt in state.players[player].commander_damage.items():
        if dealt >= COMMANDER_DAMAGE_LOSS:
            return name
    return None
