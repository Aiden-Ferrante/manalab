"""What a player may legally do right now.

The engine never asks an agent an open question. It enumerates the legal actions
and asks it to pick one, which means an agent cannot cheat by proposing
something illegal, and an illegal-move bug becomes an engine bug rather than a
silent rules violation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import manalab.engine.combat as combat
import manalab.engine.resolve as resolve
import manalab.engine.targets as targets
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
    targets: tuple[targets.Target, ...] = ()
    """Chosen on announcement (CR 601.2c), re-checked on resolution (CR 608.2b)."""

    def describe(self, state: GameState) -> str:
        name = state.objects[self.object_id].card.name
        if not self.targets:
            return f"cast {name}"
        chosen = ", ".join(t.describe(state) for t in self.targets)
        return f"cast {name} -> {chosen}"


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
        if not can_pay(state, player, obj.card.cost):
            continue
        actions.extend(_castings(state, player, obj))

    return actions


MAX_TARGET_OPTIONS = 64
"""Cap on distinct target choices offered for one spell.

A two-target spell on a wide board is quadratic. The cap keeps the action list
readable; it restricts the caster's options and never offers an illegal one.
"""


def _castings(state: GameState, player: int, obj) -> list[CastSpell]:
    """Every way to cast this spell, one per legal choice of targets.

    A permanent, or a spell the engine cannot resolve, is a single option with no
    targets — the resolver reports it as unmodeled and it goes to the graveyard
    having done nothing, exactly as before.

    A spell that *needs* a target and has none available cannot be cast at all
    (CR 601.2c). Offering it anyway is how a removal spell gets "cast" into an
    empty board and quietly does nothing, which reads as a play mistake rather
    than an engine bug.
    """
    if obj.card.is_permanent:
        return [CastSpell(obj.id)]

    plan = resolve.plan_for(obj.card)
    if plan is None:
        return [CastSpell(obj.id)]

    specs = plan.specs
    if not specs:
        return [CastSpell(obj.id)]

    choices: list[tuple[targets.Target, ...]] = [()]
    for spec in specs:
        available = targets.legal_targets(state, player, spec)
        if not available:
            return []  # no legal target: the spell cannot be cast
        grown: list[tuple[targets.Target, ...]] = []
        for prefix in choices:
            for target in available:
                if len(grown) >= MAX_TARGET_OPTIONS:
                    break
                grown.append(prefix + (target,))
        choices = grown

    return [CastSpell(obj.id, tuple(choice)) for choice in choices]


MAX_ATTACK_OPTIONS = 4096
"""Cap on enumerated attack subsets — the power set is 2^creatures.

Past this width the enumeration keeps every subset of the strongest attackers
and holds the rest back as a block, which still spans "swing with everything"
through "swing with nothing" but stops a fifteen-creature board from generating
thirty-two thousand options nobody will read.
"""


def legal_attacks(state: GameState, player: int) -> list[DeclareAttackers]:
    """Attack declarations available to the active player.

    Enumerates every subset of able attackers, capped at `MAX_ATTACK_OPTIONS`.
    A real agent should be handed a policy over attackers rather than the full
    power set; this exists so that exhaustive play-testing of small games is
    possible.
    """
    able = [obj for obj in state.creatures(player) if obj.can_attack]
    if not able:
        return [DeclareAttackers(())]

    # Strongest first, so that a truncated enumeration keeps the choices that
    # matter and freezes the chaff into the always-attacking tail.
    able.sort(key=lambda o: (o.power, o.toughness), reverse=True)

    width = MAX_ATTACK_OPTIONS.bit_length() - 1
    free = [o.id for o in able[:width]]
    forced = tuple(o.id for o in able[width:])

    subsets: list[DeclareAttackers] = []
    for mask in range(1 << len(free)):
        chosen = tuple(free[i] for i in range(len(free)) if mask & (1 << i))
        subsets.append(DeclareAttackers(chosen + forced if chosen else chosen))
    if forced:
        subsets.append(DeclareAttackers(()))
    return subsets


def legal_blocks(
    state: GameState, player: int, attackers: Sequence[int]
) -> tuple[list[DeclareBlockers], bool]:
    """Block assignments available to the defending player.

    Returns `(options, truncated)`. Delegates the rules to `engine.combat`:
    which pairings evasion permits, and how many assignments are affordable to
    enumerate. Each option is a *complete* assignment, so several blockers may
    block at once and they may block different attackers.
    """
    assignments, truncated = combat.legal_blocks(state, player, attackers)
    return [DeclareBlockers(a) for a in assignments], truncated
