"""Spells that do something: applying effect verbs on resolution.

Until now every instant and sorcery resolved and did nothing, and said so via
`GameResult.unmodeled`. This module is the first place where a card's parsed
`Effect` verbs actually change the game.

The verbs here share one shape — *choose a target, apply an immediate effect* —
which is why they come first. None of them needs a triggered-ability system, and
the stack and priority already exist, so a burn spell is genuinely castable in
response to something. Verbs that create continuous effects (`grant_ability`),
put objects onto the battlefield (`create_token`) or trigger on events all need
machinery that does not exist yet, and are refused rather than approximated.

**A card is all-or-nothing.** If any of its verbs or targets is unsupported, the
whole card is refused and reported — never partly executed. Half-resolving
"destroy target creature and draw a card" is worse than not implementing it,
because the result looks like a legal game.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

import manalab.engine.targets as T
from manalab.cards.model import Card, Effect
from manalab.engine.objects import GameObject
from manalab.engine.state import GameState
from manalab.engine.zones import Zone

IMPLEMENTED = frozenset(
    {"deal_damage", "destroy", "draw", "gain_life", "pump", "counter_spell"}
)

MASS_VERBS = frozenset({"deal_damage", "destroy"})
"""Verbs that may apply to a whole board.

Sweepers only. `pump` is deliberately excluded — see `unsupported`.
"""
"""Verbs this module executes. `engine.fidelity` reads this — do not duplicate it."""

_PUMP = re.compile(r"^([+-]\d+)/([+-]\d+)$")


@dataclass(frozen=True)
class Plan:
    """A resolvable spell: its verbs paired with the targets they need."""

    effects: tuple[tuple[Effect, T.TargetSpec], ...]

    @property
    def specs(self) -> tuple[T.TargetSpec, ...]:
        return tuple(spec for _, spec in self.effects if spec.needs_target)


def unsupported(card: Card) -> tuple[str, ...]:
    """Why this card cannot resolve, or empty if it can.

    Reasons are phrased for a human reading an `unmodeled` report, because that
    report is the ranked to-do list for growing the engine.
    """
    if not card.effects:
        return ("no parsed effects",)

    reasons: list[str] = []
    for effect in card.effects:
        if effect.verb not in IMPLEMENTED:
            reasons.append(f"verb not implemented: {effect.verb}")
            continue
        spec = T.parse(effect.get("target"))
        if spec is None:
            reasons.append(f"target not understood: {effect.get('target')!r}")
        elif spec.is_mass and effect.verb not in MASS_VERBS:
            # A mass pump is refused, and this is the one place where refusing
            # matters more than covering cards. A single pump is modelled as
            # counters — wrong after this turn, bounded, and documented. Applied
            # to every creature on the board it becomes a permanent global
            # anthem that also buffs the opponent, which is not an approximation
            # of the card, it is a different card.
            reasons.append(f"{effect.verb} over a whole board needs a duration model")
        if effect.verb == "pump" and _pump_amount(effect) is None:
            reasons.append(f"pump amount not understood: {effect.get('amount')!r}")
        if effect.verb in ("deal_damage", "draw", "gain_life") and \
                not isinstance(effect.get("amount", 1), int):
            reasons.append(f"amount not a number: {effect.get('amount')!r}")
    return tuple(dict.fromkeys(reasons))


def plan_for(card: Card) -> Plan | None:
    """A `Plan`, or `None` if anything about the card is unsupported."""
    if unsupported(card):
        return None
    pairs = []
    for effect in card.effects:
        spec = T.parse(effect.get("target"))
        assert spec is not None  # guaranteed by unsupported() above
        pairs.append((effect, spec))
    return Plan(tuple(pairs))


def _pump_amount(effect: Effect) -> tuple[int, int] | None:
    match = _PUMP.match(str(effect.get("amount", "")))
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def apply(
    state: GameState,
    spell: GameObject,
    chosen: Sequence[T.Target],
    log: list[str],
) -> None:
    """Resolve `spell`'s effects against the targets chosen on announcement.

    Targets are re-checked here (CR 608.2b): anything that became illegal while
    the spell was on the stack is skipped, and a spell that loses all of its
    targets does nothing.
    """
    plan = plan_for(spell.card)
    if plan is None:  # pragma: no cover - the caller checks first
        return
    _run(state, spell, plan, chosen, log)


def apply_effects(
    state: GameState,
    source: GameObject,
    effects: Sequence[Effect],
    chosen: Sequence[T.Target],
    log: list[str],
) -> None:
    """Resolve an explicit list of effects — a triggered ability's, not a card's.

    `apply` plans from `card.effects`, which is every effect the card has. A
    trigger owns only its own, so resolving one through `apply` would fire the
    whole card each time it entered.
    """
    pairs = []
    for effect in effects:
        spec = T.parse(effect.get("target"))
        if spec is None:      # refused upstream by fidelity; belt and braces
            return
        pairs.append((effect, spec))
    _run(state, source, Plan(tuple(pairs)), chosen, log)


def _run(
    state: GameState,
    spell: GameObject,
    plan: "Plan",
    chosen: Sequence[T.Target],
    log: list[str],
) -> None:

    controller = spell.controller
    queue = list(chosen)

    for effect, spec in plan.effects:
        if spec.is_mass:
            _apply_mass(state, spell, effect, log)
            continue

        target = None
        if spec.needs_target:
            if not queue:
                continue
            target = queue.pop(0)
            if not T.still_legal(state, controller, spec, target):
                log.append(f"{spell.card.name} fizzles: target is gone")
                continue
        _apply_one(state, spell, effect, target, log)


def _apply_mass(
    state: GameState, spell: GameObject, effect: Effect, log: list[str]
) -> None:
    """Apply a verb to every creature on the battlefield.

    The victim list is taken once, before anything is applied. Iterating the
    battlefield while moving creatures off it skips half of them, which would
    make a sweeper destroy every other creature and look like a shuffle bug.
    """
    victims = [obj for obj in state.creatures() if obj.zone is Zone.BATTLEFIELD]
    if not victims:
        return

    name = spell.card.name
    if effect.verb == "destroy":
        for obj in victims:
            state.move(obj, Zone.GRAVEYARD)
        log.append(f"{name} destroys all {len(victims)} creatures")
    elif effect.verb == "deal_damage":
        amount = int(effect.get("amount", 1))
        for obj in victims:
            obj.damage += amount
        log.append(f"{name} deals {amount} to each of {len(victims)} creatures")


def _apply_one(
    state: GameState,
    spell: GameObject,
    effect: Effect,
    target: T.Target | None,
    log: list[str],
) -> None:
    controller = spell.controller
    name = spell.card.name
    verb = effect.verb

    if verb == "deal_damage":
        amount = int(effect.get("amount", 1))
        if target is None:
            return
        if target.is_player:
            state.players[target.player].lose_life(amount)
            log.append(f"{name} deals {amount} to P{target.player}")
        else:
            obj = state.objects[target.object_id]
            obj.damage += amount
            log.append(f"{name} deals {amount} to {obj.card.name}")

    elif verb == "destroy":
        if target is None or target.is_player:
            return
        obj = state.objects[target.object_id]
        state.move(obj, Zone.GRAVEYARD)
        log.append(f"{name} destroys {obj.card.name}")

    elif verb == "counter_spell":
        if target is None or target.is_player:
            return
        countered = state.objects.get(target.object_id)
        if countered is None or countered.zone is not Zone.STACK:
            return
        # CR 701.5a: a countered spell goes to its owner's graveyard without
        # resolving. It never reaches the battlefield even if it is a permanent,
        # which is the entire point and the thing a naive implementation — moving
        # it after resolution — gets backwards.
        state.move(countered, Zone.GRAVEYARD)
        log.append(f"{name} counters {countered.card.name}")

    elif verb == "draw":
        amount = int(effect.get("amount", 1))
        state.draw(controller, amount)
        log.append(f"{name}: P{controller} draws {amount}")

    elif verb == "gain_life":
        amount = int(effect.get("amount", 1))
        who = target.player if (target and target.is_player) else controller
        state.players[who].gain_life(amount)
        log.append(f"{name}: P{who} gains {amount}")

    elif verb == "pump":
        amounts = _pump_amount(effect)
        if amounts is None or target is None or target.is_player:
            return
        power, toughness = amounts
        obj = state.objects[target.object_id]
        # Each half moves independently, and only until end of turn — cleared in
        # the cleanup step. This used to be modelled as counters, which are
        # symmetric by construction: the two halves were collapsed with
        # `max(power, toughness)` and applied to both. That made Nameless
        # Inversion (+3/-3) a permanent +3/+3 buff instead of a removal spell,
        # Chelonian Tackle (+0/+10) a 12/12, and every all-negative shrink
        # (-5/-0) a silent no-op. 43 of the 102 pump cards in the searchable pool
        # were executed wrongly, and `fidelity` reported all of them as faithful.
        obj.power_mod += power
        obj.toughness_mod += toughness
        log.append(f"{name} pumps {obj.card.name} {power:+}/{toughness:+}")
