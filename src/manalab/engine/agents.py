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
    ActivateAbility,
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
            return max(spells, key=lambda a: self._spell_value(state, player, a))

        # Activations come after casting deliberately: mana spent on an ability
        # is mana not spent developing the board, and this agent's whole theory
        # is curve. Only helpful ones, scored the same way spells are.
        activations = [o for o in options if isinstance(o, ActivateAbility)]
        helpful = [(self._activation_value(state, player, a), a) for a in activations]
        helpful = [(v, a) for v, a in helpful if v > 0]
        if helpful:
            return max(helpful, key=lambda pair: pair[0])[1]

        attacks = [o for o in options if isinstance(o, DeclareAttackers)]
        if attacks:
            if not self.attack_with_everything:
                return min(attacks, key=lambda a: len(a.attackers))
            return max(attacks, key=lambda a: self._attack_value(state, a))

        blocks = [o for o in options if isinstance(o, DeclareBlockers)]
        if blocks:
            return self._best_block(state, player, blocks)

        return do_nothing(options)

    @staticmethod
    def _spell_value(state: GameState, player: int, action: CastSpell) -> tuple[float, float]:
        """Rank one casting. Returns (cast priority, target quality).

        The engine hands the agent one `CastSpell` per legal choice of target, so
        without a preference here "cast the biggest thing" picks an arbitrary
        target — and since "target creature" includes your own board, the crude
        pilot will cheerfully Murder its own best creature. That is not a
        interestingly-bad play, it is a broken measuring instrument.

        Still deliberately shallow: it does not hold removal for a better threat,
        does not play around anything, and values a creature purely by its body.
        """
        card = state.objects[action.object_id].card
        verbs = {effect.verb for effect in card.effects}
        harmful = bool(verbs & {"deal_damage", "destroy", "tap"})
        helpful = bool(verbs & {"pump", "untap"})

        if "counter_spell" in verbs:
            # Countering is worth doing when it is the opponent's spell and the
            # spell is worth answering; countering your own is never right.
            quality = 0.0
            for target in action.targets:
                obj = state.objects.get(target.object_id)
                if obj is None:
                    continue
                quality += -100.0 if obj.controller == player else 5.0 + obj.card.cmc
            # Ranked above ordinary spells so a held counter actually gets used
            # rather than losing the comparison to a bigger creature.
            return (99.0, quality)

        quality = 0.0
        for target in action.targets:
            if target.is_player:
                # A harmful spell goes at the opponent; a beneficial one —
                # "target player draws three cards" — at its caster. Assuming
                # every player target was a burn spell would have this pilot
                # casting Ancestral Recall at the enemy.
                helps = bool(verbs & {"draw", "gain_life"})
                right_way = (target.player == player) if helps \
                    else (target.player != player)
                quality += 3.0 if right_way else -100.0
                continue
            obj = state.objects.get(target.object_id)
            if obj is None:
                continue
            body = obj.power + obj.toughness
            mine = obj.controller == player
            if harmful:
                quality += (-100.0 if mine else body)
            elif helpful:
                quality += (body if mine else -100.0)

        return (card.cmc, quality)

    @staticmethod
    def _attack_value(state: GameState, action: DeclareAttackers) -> tuple:
        """Most attackers first, then the softest defender.

        The multiplayer choice this pilot was missing: with three opponents,
        "attack with everything" still had to pick a face, and picking
        arbitrarily let four mirror decks chump-block each other into the turn
        cap — the first real table measured mean game length at exactly the
        cap, all draws. Softest = fewest untapped creatures, then least life.
        Still no politics: it never reasons about who is *winning*, only about
        where damage lands.
        """
        if not action.attackers or action.defender is None:
            return (len(action.attackers), 0.0)
        blockers = sum(1 for o in state.creatures(action.defender) if not o.tapped)
        life = state.players[action.defender].life
        return (len(action.attackers), -(blockers * 100 + life))

    HELPFUL = frozenset({"draw", "gain_life", "put_counters", "create_token",
                         "pump", "grant_ability", "untap", "put_from_hand"})
    HARMFUL = frozenset({"deal_damage", "destroy", "tap"})

    def _activation_value(self, state: GameState, player: int,
                          action: ActivateAbility) -> float:
        """Whether this activation is worth making. Deliberately shallow.

        An ability that helps is worth using; one that would hurt is worth using
        only at somebody else. Nothing here holds mana open, reasons about the
        opponent's board, or waits for a better moment — the pilot is a control
        for the simulation, not a player.
        """
        obj = state.objects.get(action.object_id)
        if obj is None:
            return 0.0

        score = 0.0
        for effect in obj.card.abilities[action.index].effects:
            if effect.verb in self.HELPFUL:
                score += 1.0
            elif effect.verb in self.HARMFUL:
                # Pointed at anything of ours this is a cost, not a play.
                for target in action.targets:
                    if target.is_player:
                        score += 2.0 if target.player != player else -100.0
                    else:
                        victim = state.objects.get(target.object_id)
                        score += 2.0 if victim and victim.controller != player else -100.0
        return score

    def _best_block(
        self, state: GameState, player: int, blocks: Sequence[DeclareBlockers]
    ) -> DeclareBlockers:
        """Score each complete assignment; take the best.

        Deliberately shallow — it values a trade, avoids a pointless chump, and
        chumps anyway when the alternative is dying this turn. It does not
        reason about multi-blocking a single large attacker, damage assignment
        order, or what it wants the board to look like next turn.

        Keyword-aware only where ignoring a keyword would be a *rules* mistake
        rather than a judgement one: deathtouch kills whatever it touches, and
        trample means chumping saves far less life than it appears to.
        """
        lethal_incoming = self._incoming(state, player, blocks[0]) >= state.players[player].life

        best, best_value = blocks[0], self._score(state, player, blocks[0], lethal_incoming)
        for option in blocks[1:]:
            value = self._score(state, player, option, lethal_incoming)
            if value > best_value:
                best, best_value = option, value
        return best

    @staticmethod
    def _incoming(state: GameState, player: int, no_blocks: DeclareBlockers) -> int:
        """Damage the defending player takes if nothing blocks."""
        return sum(
            obj.power
            for obj in state.battlefield()
            if obj.attacking == player and obj.power > 0
        )

    @staticmethod
    def _score(
        state: GameState, player: int, option: DeclareBlockers, lethal_incoming: bool
    ) -> float:
        value = 0.0
        blocked_damage = 0
        for blocker_id, attacker_id in option.blocks:
            blocker = state.objects[blocker_id]
            attacker = state.objects[attacker_id]

            kills = blocker.has("Deathtouch") or blocker.power >= attacker.toughness
            dies = attacker.has("Deathtouch") or attacker.power >= blocker.toughness

            # Trample means the body absorbs only up to its toughness.
            absorbed = (
                min(attacker.power, blocker.toughness)
                if attacker.has("Trample")
                else attacker.power
            )
            blocked_damage += max(0, absorbed)

            value += 2.0 if kills else 0.0
            value -= 1.0 if dies else -1.0

        if lethal_incoming:
            # Staying alive dominates every trade consideration.
            value += 10.0 * blocked_damage
        return value
