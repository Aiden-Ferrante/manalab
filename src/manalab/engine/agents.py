"""Deciding what to do, given the legal options.

The engine hands an agent a list of legal actions and takes back one of them.
An agent therefore cannot make an illegal play, and any rules violation is an
engine bug rather than a silent cheat — which is the property that makes it safe
to plug a learned policy in later.

The agents here are baselines, not good players.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Protocol, Sequence, runtime_checkable

from manalab.engine.actions import (
    Action,
    CastSpell,
    DeclareAttackers,
    DeclareBlockers,
    Pass,
    PlayLand,
)
from manalab.engine.state import GameState


@runtime_checkable
class Agent(Protocol):
    name: str

    def act(self, state: GameState, player: int, options: Sequence[Action]) -> Action:
        """Pick one of `options`. Returning anything else is an error."""


def do_nothing(options: Sequence[Action]) -> Action:
    """The most passive legal option.

    `Pass` when it is offered; otherwise the empty attack or block declaration,
    since those steps demand an answer and "none" is the passive one.
    """
    for option in options:
        if isinstance(option, Pass):
            return option
    for option in options:
        if isinstance(option, DeclareAttackers) and not option.attackers:
            return option
        if isinstance(option, DeclareBlockers) and not option.blocks:
            return option
    return options[0]


@dataclass
class PassingAgent:
    """Never does anything. The goldfish opponent.

    Useful as a control: a deck's clock against a player who never interacts is
    exactly what `manalab.game` measures, so this is how the two models get
    compared on the same question.

    "Do nothing" is not always `Pass`. Declaring attackers and blockers is a
    turn-based action that *must* be answered, and the null answer there is an
    empty declaration. An agent that only knows how to pass will crash in the
    declare-blockers step.
    """

    name: str = "passing"

    def act(self, state: GameState, player: int, options: Sequence[Action]) -> Action:
        return do_nothing(options)


@dataclass
class RandomAgent:
    name: str = "random"
    seed: int = 0
    _rng: random.Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def act(self, state: GameState, player: int, options: Sequence[Action]) -> Action:
        return self._rng.choice(list(options))


@dataclass
class CurveAgent:
    """Play a land, cast the most expensive thing you can, attack with everything.

    A deliberately crude heuristic that nonetheless plays aggro decks passably
    and control decks terribly — the same shape of weakness Forge's AI has, and
    the reason "win rate against this agent" is a proxy to treat with suspicion
    rather than a measure of deck strength.
    """

    name: str = "curve"
    attack_with_everything: bool = True

    def act(self, state: GameState, player: int, options: Sequence[Action]) -> Action:
        lands = [o for o in options if isinstance(o, PlayLand)]
        if lands:
            # Untapped first, so the mana is usable this turn.
            return min(lands, key=lambda a: state.objects[a.object_id].card.enters_tapped)

        spells = [o for o in options if isinstance(o, CastSpell)]
        if spells:
            return max(spells, key=lambda a: state.objects[a.object_id].card.cmc)

        attacks = [o for o in options if isinstance(o, DeclareAttackers)]
        if attacks:
            return max(attacks, key=lambda a: len(a.attackers)) if self.attack_with_everything \
                else min(attacks, key=lambda a: len(a.attackers))

        blocks = [o for o in options if isinstance(o, DeclareBlockers)]
        if blocks:
            return self._best_block(state, player, blocks)

        return do_nothing(options)

    def _best_block(
        self, state: GameState, player: int, blocks: Sequence[DeclareBlockers]
    ) -> DeclareBlockers:
        """Block only when the blocker survives and the attacker dies.

        Chump-blocking to save life total is often correct and this will never
        do it. That is a known weakness, not an oversight.
        """
        best, best_value = blocks[0], 0
        for option in blocks:
            value = 0
            for blocker_id, attacker_id in option.blocks:
                blocker = state.objects[blocker_id]
                attacker = state.objects[attacker_id]
                kills = blocker.power >= attacker.toughness
                survives = attacker.power < blocker.toughness
                value += (2 if kills else 0) + (1 if survives else -1)
            if value > best_value:
                best, best_value = option, value
        return best
