"""The driver: turns, priority, the stack, and combat.

Deliberately small. Everything specific to a card belongs in the effect-verb
layer, not here — the moment this file starts naming cards, the engine has
stopped being growable.

What resolving a spell currently does: permanents go to the battlefield,
everything else goes to the graveyard having done nothing. That is wrong for
every instant and sorcery in the game, and `GameResult.unmodeled` says so by
name. A rules engine that silently does nothing is far more dangerous than a
goldfish sim that advertises its blind spots, so nothing here is allowed to fail
quietly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import manalab.engine.actions as A
import manalab.engine.combat as combat
import manalab.engine.mana as mana
import manalab.engine.resolve as resolve
import manalab.engine.sba as sba
from manalab.engine.agents import Agent
from manalab.engine.objects import GameObject
from manalab.engine.state import GameState
from manalab.engine.steps import NO_PRIORITY, TURN, Step
from manalab.engine.zones import Zone

MAX_TURNS = 40


@dataclass
class GameResult:
    winner: int | None
    """None means a draw, or the turn limit was reached."""
    turns: int
    reason: str
    unmodeled: dict[str, str] = field(default_factory=dict)
    """Cards the engine could not represent. Read this before believing a result."""
    life: tuple[int, ...] = ()
    log: list[str] = field(default_factory=list)

    @property
    def decisive(self) -> bool:
        return self.winner is not None


class Game:
    def __init__(
        self,
        state: GameState,
        agents: Sequence[Agent],
        *,
        max_turns: int = MAX_TURNS,
        opening_hand: int = 7,
    ) -> None:
        if len(agents) != len(state.players):
            raise ValueError("need one agent per player")
        self.state = state
        self.agents = list(agents)
        self.max_turns = max_turns
        self.opening_hand = opening_hand
        self.unmodeled: dict[str, str] = {}
        self._targets: dict[int, tuple] = {}
        """Targets chosen on announcement, keyed by the spell's id on the stack."""

    # --- setup ----------------------------------------------------------

    def setup(self) -> None:
        for index in range(len(self.state.players)):
            self.state.shuffle(index)
            self.state.draw(index, self.opening_hand)

    # --- main loop ------------------------------------------------------

    def run(self) -> GameResult:
        self.setup()

        while self.state.turn < self.max_turns and not sba.game_over(self.state):
            self._play_turn()

        winner = sba.winner(self.state)
        if winner is not None:
            reason = self.state.players[1 - winner].loss_reason or "opponent lost"
        elif sba.game_over(self.state):
            reason = "all players lost"
        else:
            reason = f"turn limit ({self.max_turns})"

        return GameResult(
            winner=winner,
            turns=self.state.turn,
            reason=reason,
            unmodeled=dict(self.unmodeled),
            life=tuple(p.life for p in self.state.players),
            log=list(self.state.log),
        )

    def _play_turn(self) -> None:
        state = self.state
        state.turn += 1
        state.active_player = (state.turn - 1) % len(state.players)
        state.players[state.active_player].begin_turn()
        state.log.append(f"--- turn {state.turn} ({state.players[state.active_player].name})")

        for step in TURN:
            if sba.game_over(state):
                return
            self._turn_based_action(step)
            if step not in NO_PRIORITY and not self._combat_skipped(step):
                self._priority(step)

    def _combat_skipped(self, step: Step) -> bool:
        """No attackers means no blockers and no combat damage (CR 508.1e)."""
        if step not in (Step.DECLARE_BLOCKERS, Step.COMBAT_DAMAGE):
            return False
        return not self._attackers()

    # --- turn-based actions ---------------------------------------------

    def _turn_based_action(self, step: Step) -> None:
        state = self.state
        active = state.active_player

        if step is Step.UNTAP:
            state.untap_all(active)
        elif step is Step.DRAW:
            # The player on the play skips their first draw.
            if state.turn > 1:
                state.draw(active)
        elif step is Step.DECLARE_ATTACKERS:
            self._declare_attackers()
        elif step is Step.DECLARE_BLOCKERS:
            if self._attackers():
                self._declare_blockers()
        elif step is Step.COMBAT_DAMAGE:
            if self._attackers():
                self._combat_damage()
        elif step is Step.END_COMBAT:
            for obj in state.battlefield():
                obj.leave_combat()
        elif step is Step.CLEANUP:
            for obj in state.battlefield():
                obj.damage = 0
                obj.deathtouched = False

    # --- priority -------------------------------------------------------

    def _priority(self, step: Step) -> None:
        state = self.state
        n = len(state.players)
        player = state.active_player
        passes = 0

        for _ in range(10_000):  # guards against an agent that never passes
            sba.check(state)
            if sba.game_over(state):
                return

            stack = state.zone(Zone.STACK)
            if state.players[player].has_lost:
                player = (player + 1) % n
                passes += 1
            else:
                options = A.legal(state, player, step, stack_empty=not stack)
                choice = self.agents[player].act(state, player, options)
                if choice not in options:
                    raise ValueError(f"{self.agents[player].name} chose an illegal action")

                if isinstance(choice, A.Pass):
                    passes += 1
                    player = (player + 1) % n
                else:
                    self._apply(player, choice)
                    # CR 117.3c: after acting you get priority again.
                    passes = 0
                    continue

            if passes >= n:
                if stack:
                    self._resolve_top()
                    passes = 0
                    player = state.active_player
                else:
                    return
        raise RuntimeError(f"priority did not terminate in {step}")

    def _apply(self, player: int, action: A.Action) -> None:
        state = self.state
        if isinstance(action, A.PlayLand):
            # Playing a land uses no stack and cannot be responded to.
            state.move(state.objects[action.object_id], Zone.BATTLEFIELD, controller=player)
            state.players[player].lands_played += 1
        elif isinstance(action, A.CastSpell):
            obj = state.objects[action.object_id]
            mana.pay(state, player, obj.card.cost)
            moved = state.move(obj, Zone.STACK, controller=player)
            # A card changing zones becomes a new object (CR 400.7), so the
            # targets have to be filed under the id it has *on the stack*.
            # Keying them by the hand id leaves every spell resolving untargeted.
            if action.targets:
                self._targets[moved.id] = action.targets
        else:  # pragma: no cover - the priority loop offers nothing else
            raise NotImplementedError(action)

    def _resolve_top(self) -> None:
        state = self.state
        stack = state.zone(Zone.STACK)
        top = stack[-1]

        if top.card.is_permanent:
            state.move(top, Zone.BATTLEFIELD, controller=top.controller)
            return

        chosen = self._targets.pop(top.id, ())
        blocked = resolve.unsupported(top.card)
        if blocked:
            self.unmodeled.setdefault(top.card.name, "; ".join(blocked))
        else:
            resolve.apply(state, top, chosen, state.log)

        state.move(top, Zone.GRAVEYARD)

    # --- combat ---------------------------------------------------------

    def _attackers(self) -> list[GameObject]:
        return [o for o in self.state.battlefield() if o.attacking is not None]

    def _declare_attackers(self) -> None:
        state = self.state
        active = state.active_player
        options = A.legal_attacks(state, active)
        choice = self.agents[active].act(state, active, options)
        if not isinstance(choice, A.DeclareAttackers):
            raise ValueError("expected an attack declaration")

        defender = (active + 1) % len(state.players)
        for obj_id in choice.attackers:
            attacker = state.objects[obj_id]
            attacker.attacking = defender
            if not attacker.has("Vigilance"):
                attacker.tapped = True
        if choice.attackers:
            state.log.append(f"attacks: {[state.objects[i].card.name for i in choice.attackers]}")

    def _declare_blockers(self) -> None:
        state = self.state
        attackers = [o.id for o in self._attackers()]
        defender = (state.active_player + 1) % len(state.players)

        options, truncated = A.legal_blocks(state, defender, attackers)
        if truncated:
            self.unmodeled.setdefault(
                "<block enumeration>",
                "board too wide to enumerate every block; weakest blockers held back",
            )
        choice = self.agents[defender].act(state, defender, options)
        if not isinstance(choice, A.DeclareBlockers):
            raise ValueError("expected a block declaration")

        for blocker_id, attacker_id in choice.blocks:
            blocker = state.objects[blocker_id]
            attacker = state.objects[attacker_id]
            blocker.blocking = attacker_id
            attacker.blocked_by = attacker.blocked_by + (blocker_id,)

    def _combat_damage(self) -> None:
        """Combat damage, as a first-strike pass followed by a regular one.

        The first pass is skipped entirely when nobody in combat has first or
        double strike, which is the overwhelmingly common case — and state-based
        actions run between the passes, so a creature killed by first strike
        never gets to strike back.
        """
        state = self.state
        attackers = self._attackers()

        if combat.any_first_strike(attackers, state):
            for line in combat.combat_damage(state, attackers, first_strike_pass=True):
                state.log.append(line)
            sba.check(state)
            attackers = self._attackers()

        for line in combat.combat_damage(state, attackers, first_strike_pass=False):
            state.log.append(line)

        if any(o.card.taps_for_mana for o in state.battlefield()):
            self.unmodeled.update(mana.unmodeled_sources(state))
