"""What a player may legally do right now.

The engine never asks an agent an open question. It enumerates the legal actions
and asks it to pick one, which means an agent cannot cheat by proposing
something illegal, and an illegal-move bug becomes an engine bug rather than a
silent rules violation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from manalab.engine.mana import can_pay
from manalab.engine.state import GameState
from manalab.engine.steps import Step, is_sorcery_speed
from manalab.engine.zones import Zone


@dataclass(frozen=True)
class Action:
    """Base class. Subclasses are the vocabulary an agent chooses from."""

    def describe(self, state: GameState) -> str:
        return type(self).__name__


@dataclass(frozen=True)
class Pass(Action):
    def describe(self, state: GameState) -> str:
        return "pass"


@dataclass(frozen=True)
class PlayLand(Action):
    object_id: int

    def describe(self, state: GameState) -> str:
        return f"play {state.objects[self.object_id].card.name}"


@dataclass(frozen=True)
class CastSpell(Action):
    object_id: int

    def describe(self, state: GameState) -> str:
        return f"cast {state.objects[self.object_id].card.name}"


@dataclass(frozen=True)
class DeclareAttackers(Action):
    attackers: tuple[int, ...] = ()

    def describe(self, state: GameState) -> str:
        if not self.attackers:
            return "attack with nothing"
        names = ", ".join(state.objects[i].card.name for i in self.attackers)
        return f"attack with {names}"


@dataclass(frozen=True)
class DeclareBlockers(Action):
    blocks: tuple[tuple[int, int], ...] = ()
    """(blocker_id, attacker_id) pairs."""

    def describe(self, state: GameState) -> str:
        return f"block {len(self.blocks)}" if self.blocks else "no blocks"


def legal(state: GameState, player: int, step: Step, *, stack_empty: bool) -> list[Action]:
    """Every action `player` may take with priority in `step`.

    Always includes `Pass`: a player may always decline to act, and a priority
    loop that can produce an empty action list will deadlock.
    """
    actions: list[Action] = [Pass()]
    active = state.active_player == player
    sorcery_speed = is_sorcery_speed(step, active, stack_empty)

    hand = state.hand(player)

    if sorcery_speed and state.players[player].can_play_land():
        actions.extend(PlayLand(obj.id) for obj in hand if obj.is_land)

    for obj in hand:
        if obj.is_land:
            continue
        # Sorceries and creatures need sorcery speed; instants do not. Flash is
        # not yet modelled, so a flash creature is currently over-restricted.
        instant_speed = "Instant" in obj.types or obj.has("Flash")
        if not (instant_speed or sorcery_speed):
            continue
        if can_pay(state, player, obj.card.cost):
            actions.append(CastSpell(obj.id))

    return actions


def legal_attacks(state: GameState, player: int) -> list[DeclareAttackers]:
    """Attack declarations available to the active player.

    Enumerates every subset of able attackers, so it is exponential and only
    safe on small boards. A real agent should be handed a policy over
    attackers rather than the full power set; this exists so that exhaustive
    play-testing of small games is possible.
    """
    able = [obj.id for obj in state.creatures(player) if obj.can_attack]
    if not able:
        return [DeclareAttackers(())]

    subsets: list[DeclareAttackers] = []
    for mask in range(1 << len(able)):
        chosen = tuple(able[i] for i in range(len(able)) if mask & (1 << i))
        subsets.append(DeclareAttackers(chosen))
    return subsets


def legal_blocks(
    state: GameState, player: int, attackers: Sequence[int]
) -> list[DeclareBlockers]:
    """Block assignments available to the defending player.

    Restricted to at most one blocker per attacker and no multi-blocking, which
    covers the common case and keeps the branching factor sane. Multi-blocks and
    damage assignment order are not yet modelled.
    """
    able = [obj.id for obj in state.creatures(player) if not obj.tapped]
    if not able or not attackers:
        return [DeclareBlockers(())]

    options: list[DeclareBlockers] = [DeclareBlockers(())]
    for blocker in able:
        for attacker in attackers:
            options.append(DeclareBlockers(((blocker, attacker),)))
    return options
