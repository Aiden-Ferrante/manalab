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
import manalab.engine.commander as commander
import manalab.engine.mana as mana
import manalab.engine.resolve as resolve
import manalab.engine.activation as activation
import manalab.engine.sba as sba
import manalab.engine.statics as statics
import manalab.engine.triggers as triggers
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
            losers = [p for p in self.state.players if p.index != winner]
            reason = next((p.loss_reason for p in losers if p.loss_reason),
                          "opponents lost")
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
        for obj in state.battlefield():
            obj.loyalty_used = False
        state.log.append(f"--- turn {state.turn} ({state.players[state.active_player].name})")

        for step in TURN:
            if sba.game_over(state):
                return
            self._turn_based_action(step)
            if step not in NO_PRIORITY and not self._combat_skipped(step):
                self._priority(step)
            # CR 500.4: mana empties at the end of every step and phase.
            # Without this the pool is a bank account and a ritual cast on
            # turn one pays for a spell on turn six.
            for player in state.players:
                player.mana_pool.clear()

    def _combat_skipped(self, step: Step) -> bool:
        """No attackers means no blockers and no combat damage (CR 508.1e)."""
        if step not in (Step.DECLARE_BLOCKERS, Step.COMBAT_DAMAGE):
            return False
        return not self._attackers()

    # --- turn-based actions ---------------------------------------------

    _STEP_EVENTS = {
        Step.UPKEEP: triggers.EventKind.UPKEEP,
        Step.END: triggers.EventKind.END_STEP,
        Step.BEGIN_COMBAT: triggers.EventKind.BEGIN_COMBAT,
    }

    def _turn_based_action(self, step: Step) -> None:
        state = self.state
        active = state.active_player

        # "At the beginning of your upkeep" belongs to the active player, so
        # the event carries them and matching scans their battlefield.
        kind = self._STEP_EVENTS.get(step)
        if kind is not None:
            state.events.append(triggers.Event(kind, None, active))

        if step is Step.UNTAP:
            state.untap_all(active)
            # Seedborn's line: permanents that untap during OTHER players'
            # untap steps. Asked of the battlefield each untap step rather
            # than cached, so the effect leaves when its source does.
            for obj in state.battlefield():
                if obj.controller != active and \
                        statics.untaps_during_others(obj.card):
                    state.untap_all(obj.controller)
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
                # "Until end of turn" ends here (CR 514.2). Without this a pump
                # would last the rest of the game, which is the lie the old
                # counter-based modelling made permanent.
                obj.power_mod = 0
                obj.toughness_mod = 0
                obj.granted.clear()

    # --- priority -------------------------------------------------------

    def _priority(self, step: Step) -> None:
        state = self.state
        n = len(state.players)
        player = state.active_player
        passes = 0

        for _ in range(10_000):  # guards against an agent that never passes
            # Before SBAs, because an anthem leaving can put a creature at
            # zero toughness and that death is what SBAs are checking for.
            statics.apply(state)
            sba.check(state)
            if sba.game_over(state):
                return
            # CR 117.5: triggers that have waited since the last priority go
            # on the stack now, after state-based actions and before anyone
            # acts — so they can be responded to, like any other object.
            self._collect_triggers()

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

    def _collect_triggers(self) -> None:
        """Put every ability watching a recent event onto the stack."""
        state = self.state
        if not state.events:
            return
        pending, state.events = state.events, []

        def fire(watcher, ability) -> None:
            entry = state.create(watcher.card, owner=watcher.owner,
                                 zone=Zone.STACK, controller=watcher.controller)
            entry.trigger = ability
            entry.source_id = watcher.id
            state.log.append(f"trigger: {watcher.card.name} ({event.kind.value})")

        for event in pending:
            if event.kind in triggers.STEP_EVENTS:
                # Happened to a player, so everything they control is watching.
                for watcher in state.battlefield(event.controller):
                    for watch, ability in triggers.watched_by(watcher.card):
                        if watch.kind is event.kind and not watch.is_self:
                            fire(watcher, ability)
                continue

            subject = state.objects.get(event.object_id)
            if subject is None:
                continue        # it moved again before triggers were collected

            # The thing's own event — enters, dies, attacks — fires from the
            # subject itself, wherever it now is (a dies trigger's source is
            # already in the graveyard).
            for ability in triggers.fired_by(subject.card, event.kind):
                fire(subject, ability)

            # The ChangesZone family: everything on the battlefield watching
            # for events like this one. "A land you control enters" is checked
            # against the subject's type and the DEAD-OR-ENTERING thing's
            # controller (the event's), not the watcher's zone history.
            for watcher in state.battlefield():
                for watch, ability in triggers.watched_by(watcher.card):
                    if watch.kind is not event.kind or watch.is_self \
                            or not watch.subject:
                        continue
                    if watch.subject.capitalize() not in subject.card.type_line:
                        continue
                    if watch.yours and event.controller != watcher.controller:
                        continue
                    if watch.excludes_self and watcher.id == subject.id:
                        continue
                    fire(watcher, ability)

    def _apply(self, player: int, action: A.Action) -> None:
        state = self.state
        if isinstance(action, A.PlayLand):
            # Playing a land uses no stack and cannot be responded to.
            state.move(state.objects[action.object_id], Zone.BATTLEFIELD, controller=player)
            state.players[player].lands_played += 1
        elif isinstance(action, A.CastSpell):
            obj = state.objects[action.object_id]
            cost = obj.card.cost
            if obj.zone == Zone.COMMAND:
                cost = commander.cost_from_command_zone(state, obj)
                commander.note_cast(state, player)
            mana.pay(state, player, cost)
            moved = state.move(obj, Zone.STACK, controller=player)
            # A card changing zones becomes a new object (CR 400.7), so the
            # targets have to be filed under the id it has *on the stack*.
            # Keying them by the hand id leaves every spell resolving untargeted.
            if action.targets:
                self._targets[moved.id] = action.targets
        elif isinstance(action, A.ActivateAbility):
            obj = state.objects[action.object_id]
            ability = obj.card.abilities[action.index]
            cost = activation.parse_activation_cost(ability.cost)
            mana.pay(state, player, cost.mana)
            if cost.taps:
                obj.tapped = True
            if cost.loyalty is not None:
                # One loyalty ability per walker per turn (CR 606.3); the
                # enumerator already filtered, this is the payment itself.
                obj.add_counters("loyalty", cost.loyalty)
                obj.loyalty_used = True
            # An activated ability goes on the stack as its own object, exactly
            # as a trigger does — it is not the permanent, and the permanent
            # stays put when it resolves.
            entry = state.create(obj.card, owner=obj.owner, zone=Zone.STACK,
                                 controller=player)
            entry.trigger = ability
            entry.source_id = obj.id
            if cost.sacrifices_self:
                # Paid after the ability is on the stack, so the ability
                # resolves even though its source is dead — costs are paid on
                # activation, and dies triggers fire like any other death.
                state.move(obj, Zone.GRAVEYARD)
            if action.targets:
                self._targets[entry.id] = action.targets
            state.log.append(f"activates {obj.card.name} #{action.index}")
        else:  # pragma: no cover - the priority loop offers nothing else
            raise NotImplementedError(action)

    def _resolve_top(self) -> None:
        state = self.state
        stack = state.zone(Zone.STACK)
        top = stack[-1]

        if top.trigger is not None:
            # A triggered ability is its own object: it resolves, does its
            # thing, and ceases to exist. The permanent that made it stays
            # exactly where it is.
            chosen = self._targets.pop(top.id, ())
            resolve.apply_effects(state, top, top.trigger.effects, chosen, state.log)
            state.cease(top)
            return

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

        defender = choice.defender
        for obj_id in choice.attackers:
            attacker = state.objects[obj_id]
            attacker.attacking = defender
            state.events.append(
                triggers.Event(triggers.EventKind.ATTACKS, attacker.id, active))
            if not attacker.has("Vigilance"):
                attacker.tapped = True
        if choice.attackers:
            state.log.append(f"attacks: {[state.objects[i].card.name for i in choice.attackers]}")

    def _declare_blockers(self) -> None:
        """Each attacked player declares blocks, with their own creatures.

        The defender used to be "the next player round the table", which is only
        the right answer at two. A player who is not being attacked does not
        block, and a player who is blocks with what they control — so this is
        driven by `attacking`, which already records who each attacker chose.
        """
        state = self.state
        by_defender: dict[int, list[int]] = {}
        for obj in self._attackers():
            by_defender.setdefault(obj.attacking, []).append(obj.id)

        for defender, attackers in sorted(by_defender.items()):
            if state.players[defender].has_lost:
                continue
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
