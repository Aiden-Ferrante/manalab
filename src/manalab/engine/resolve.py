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
from manalab.cards.mana import parse_cost
from manalab.cards.model import Card, Effect
from manalab.engine.objects import COMBAT_KEYWORDS, GameObject
from manalab.engine.state import GameState
from manalab.engine.zones import Zone

IMPLEMENTED = frozenset(
    {"deal_damage", "destroy", "draw", "gain_life", "pump", "counter_spell",
     "put_counters", "shuffle", "search_library", "reveal",
     "create_token", "grant_ability", "add_mana", "ability_word",
     "tap", "untap"}
)

COUNTER_KINDS = frozenset({"+1/+1", "-1/-1"})
"""Counter kinds that actually change anything here.

A `charge` or `loyalty` counter can be *stored* on an object — `add_counters`
takes any string — but nothing reads it, so a card that cares about one would
be admitted and then quietly do nothing. Only the two `power`/`toughness`
read are accepted; the rest are refused by name."""

# `search_library` arrives as one free-text clause — the parser swallows the
# whole "find X, put it somewhere, then shuffle" sentence into a single `what`.
# There are 461 distinct shapes across 806 uses and the commonest is only 7.4%,
# so there is no general implementation to write here; there is a short list of
# shapes that mean exactly one thing. These are the basic-land fetches, which is
# the green ramp package — 152 of the 806. Everything else is refused by name.
_FETCH = (
    (re.compile(r"^an? basic land card, put (?:it|that card) onto the battlefield"
                r"(?P<tapped> tapped)?, then shuffle$", re.I), 1, "battlefield"),
    (re.compile(r"^up to two basic land cards, put them onto the battlefield"
                r"(?P<tapped> tapped)?, then shuffle$", re.I), 2, "battlefield"),
    (re.compile(r"^an? basic land card, reveal it, put it into your hand,"
                r" then shuffle$", re.I), 1, "hand"),
    # A basic type by name — "a Forest card" — is still a basic-land fetch. The
    # engine does not model choosing *which*, and takes the first match, which is
    # the same approximation as every other fetch here.
    (re.compile(r"^an? (?:forest|island|swamp|mountain|plains) card,"
                r" put (?:it|that card) onto the battlefield(?P<tapped> tapped)?,"
                r" then shuffle$", re.I), 1, "battlefield"),
)

# Cultivate and Kodama's Reach: two lands, one to each place. Split
# destinations do not fit the (count, destination) shape above, so they get
# their own entry rather than being bent into it.
_SPLIT_FETCH = re.compile(
    r"^up to two basic land cards, reveal those cards, put one onto the"
    r" battlefield tapped and the other into your hand, then shuffle$", re.I)


def _fetch_plan(effect: Effect) -> tuple[int, str, bool] | None:
    """(how many, where to, tapped) for a search clause, or None to refuse it."""
    what = str(effect.get("what", "")).strip().rstrip(".")
    if _SPLIT_FETCH.match(what):
        return 2, "split", True
    for pattern, count, destination in _FETCH:
        match = pattern.match(what)
        if match:
            tapped = bool(match.groupdict().get("tapped"))
            return count, destination, tapped
    return None


# Revealing changes what opponents know, not what is on the board, and this
# engine has no hidden-information model for it to matter to — so for a card
# already being found or drawn it is genuinely a no-op. Only the back-references
# are accepted. `reveal` also arrives carrying swallowed *cost* text on some
# cards ("a Dinosaur card from your hand or pay {1}"), and treating one of those
# as a no-op would skip a cost the player has to pay.
_REVEAL_NOOP = frozenset({"it", "them", "those cards", "that card", "this card"})

# "1/1 white Soldier creature", "2/2 black Zombie creature" — a plain body, which
# is a thing this engine can represent completely. Deliberately anchored: a
# descriptor carrying "with" has keywords or an ability after it, and Treasure,
# Food, Blood and Powerstone (291 + 129 + 35 + 32 uses) are artifacts whose whole
# point is an activated ability there is nowhere to run. All refused.
_TOKEN = re.compile(
    r"^(?P<power>\d+)/(?P<toughness>\d+) "
    r"(?P<descriptor>[a-z][a-z ]*?)(?: artifact)? creature$", re.I)


def _token_card(effect: Effect) -> Card | None:
    """The `Card` a create-token effect makes, or None to refuse it."""
    what = str(effect.get("what", "")).strip().rstrip(".")
    match = _TOKEN.match(what)
    if match is None:
        return None
    words = match.group("descriptor").split()
    # The last word is the creature type; anything before it is colour and
    # supertypes, which a token that is never cast does not need modelled.
    subtype = words[-1].capitalize() if words else "Token"
    return Card(
        oracle_id=f"token:{what}",
        name=subtype,
        cost=parse_cost(None),
        type_line=f"Token Creature — {subtype}",
        power=match.group("power"),
        toughness=match.group("toughness"),
        oracle_text="",
    )

_MANA_SYMBOLS = re.compile(r"\{([wubrgc])\}", re.I)


def _mana_added(effect: Effect) -> dict[str, int] | None:
    """The mana an `add_mana` effect makes, or None to refuse it.

    Only plain colour symbols. "{G}{G}" is three characters of unambiguous
    meaning; "one mana of any color" and "{C} for each creature you control" are
    choices and counts this has nowhere to make.
    """
    raw = str(effect.get("mana", "")).strip()
    symbols = _MANA_SYMBOLS.findall(raw)
    if not symbols or _MANA_SYMBOLS.sub("", raw).strip():
        return None
    out: dict[str, int] = {}
    for symbol in symbols:
        key = symbol.upper()
        out[key] = out.get(key, 0) + 1
    return out


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
        if effect.verb == "add_mana" and _mana_added(effect) is None:
            reasons.append(f"mana not understood: {effect.get('mana')!r}")
        if effect.verb == "grant_ability":
            granted = str(effect.get("ability", "")).strip().lower()
            if granted not in COMBAT_KEYWORDS:
                reasons.append(f"cannot grant: {granted!r}")
        if effect.verb == "create_token":
            if _token_card(effect) is None:
                reasons.append(f"token not modelled: {effect.get('what')!r}")
            if not isinstance(effect.get("amount", 1), int):
                reasons.append(f"token count not a number: {effect.get('amount')!r}")
        if effect.verb == "reveal" and \
                str(effect.get("what", "")).strip().rstrip(".").lower() not in _REVEAL_NOOP:
            reasons.append(f"reveal not understood: {effect.get('what')!r}")
        if effect.verb == "search_library" and _fetch_plan(effect) is None:
            reasons.append(f"library search not understood: {effect.get('what')!r}")
        if effect.verb == "put_counters":
            kind = str(effect.get("kind", ""))
            if kind not in COUNTER_KINDS:
                reasons.append(f"counter kind not modelled: {kind!r}")
            if not isinstance(effect.get("amount", 1), int):
                reasons.append(f"counter amount not a number: {effect.get('amount')!r}")
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
        # "Target player draws three cards" draws for the target, not the
        # caster — the drop that had Ancestral Recall drawing for the wrong
        # player. No target means the caster, as before.
        who = target.player if (target and target.is_player) else controller
        state.draw(who, amount)
        log.append(f"{name}: P{who} draws {amount}")

    elif verb in ("tap", "untap"):
        if target is None or target.is_player:
            return
        obj = state.objects[target.object_id]
        obj.tapped = verb == "tap"
        log.append(f"{name} {verb}s {obj.card.name}")

    elif verb == "gain_life":
        amount = int(effect.get("amount", 1))
        who = target.player if (target and target.is_player) else controller
        state.players[who].gain_life(amount)
        log.append(f"{name}: P{who} gains {amount}")

    elif verb == "put_counters":
        # Counters are permanent, unlike `pump` — that difference is the whole
        # point of the two verbs, and it is why this one does not touch the
        # until-end-of-turn modifiers.
        if target is None or target.is_player:
            return
        obj = state.objects[target.object_id]
        kind = str(effect.get("kind", "+1/+1"))
        amount = int(effect.get("amount", 1))
        obj.add_counters(kind, amount)
        log.append(f"{name} puts {amount} {kind} on {obj.card.name}")

    elif verb == "search_library":
        plan = _fetch_plan(effect)
        if plan is None:  # pragma: no cover - unsupported() refuses these first
            return
        count, destination, tapped = plan
        found = [o for o in state.library(controller)
                 if o.card.is_land and "Basic" in o.card.type_line][:count]
        for index, obj in enumerate(found):
            # "split" is Cultivate's shape: the first land hits the battlefield
            # tapped, the second goes to hand.
            if destination == "split":
                zone = Zone.BATTLEFIELD if index == 0 else Zone.HAND
            else:
                zone = Zone.BATTLEFIELD if destination == "battlefield" else Zone.HAND
            new = state.move(obj, zone, controller=controller)
            if zone is Zone.BATTLEFIELD and tapped:
                new.tapped = True
            log.append(f"{name}: fetches {new.card.name} to {zone}")
        # The shuffle happens whether or not anything was found — failing to find
        # is a legal outcome and still shuffles.
        state.shuffle(controller)

    elif verb == "ability_word":
        # CR 207.2c: an ability word has no rules meaning. Landfall, threshold,
        # delirium and the rest are italic labels that group similar abilities;
        # the ability they label is parsed separately and keeps its own trigger,
        # which was checked rather than assumed. A no-op here is the rules being
        # followed, not a gap being papered over.
        pass

    elif verb == "add_mana":
        added = _mana_added(effect)
        if added is None:  # pragma: no cover - unsupported() refuses these first
            return
        pool = state.players[controller].mana_pool
        for color, count in added.items():
            pool[color] = pool.get(color, 0) + count
        log.append(f"{name}: adds {added} to P{controller}'s pool")

    elif verb == "grant_ability":
        if target is None or target.is_player:
            return
        obj = state.objects[target.object_id]
        obj.granted.add(str(effect.get("ability", "")).strip().lower())
        log.append(f"{name} grants {effect.get('ability')} to {obj.card.name}")

    elif verb == "create_token":
        token = _token_card(effect)
        if token is None:  # pragma: no cover - unsupported() refuses these first
            return
        for _ in range(int(effect.get("amount", 1))):
            # Through `create`, so it fires enters-the-battlefield triggers — a
            # token entering triggers exactly as a cast creature does.
            state.create(token, owner=controller, zone=Zone.BATTLEFIELD)
        log.append(f"{name}: creates {effect.get('amount', 1)} {token.name}")

    elif verb == "reveal":
        # A no-op by design, not by omission: nothing about the board changes,
        # and the engine has no hidden information for it to reveal.
        log.append(f"{name}: reveals {effect.get('what')}")

    elif verb == "shuffle":
        state.shuffle(controller)
        log.append(f"{name}: P{controller} shuffles")

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
