"""Triggered abilities: the events, and which abilities are watching for them.

Magic's most common ability shape is "when something happens, do this" — 14,481
triggered abilities in the corpus, against roughly 18,000 activated-or-spell
ones. Until now the engine had no notion of an event at all, so a creature with
an enters-the-battlefield trigger resolved onto the battlefield and did nothing,
silently, forever. `fidelity` had to refuse the whole class to stop search from
treating Elvish Visionary as a vanilla 1/1.

This module is deliberately the narrow slice with the best ratio: **triggers a
permanent has about itself**, entering and dying. Measured over the corpus, the
self-referential enters family alone is ~3,992 abilities and dies adds ~481 —
together over a quarter of every triggered ability printed.

Everything else is refused rather than guessed at, which is the same contract
`targets` keeps. A trigger we cannot recognise makes its card unfaithful, so it
never reaches a search pool, so nothing optimises against a trigger the engine
would have silently dropped.

Recognised: the self-referential families (enters, dies, attacks, deals combat
damage to a player) and the step families that belong to their controller
(upkeep, end step, beginning of combat). Together roughly 5,800 abilities.

Not yet: the "another permanent you control" family, which needs an event to
carry a subject distinct from the ability's source, and the cast triggers, which
need an event on the stack rather than on the battlefield.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from manalab.cards.model import Ability, Card


class EventKind(Enum):
    ENTERS = "enters"
    DIES = "dies"
    ATTACKS = "attacks"
    COMBAT_DAMAGE_TO_PLAYER = "combat damage to a player"
    UPKEEP = "upkeep"
    END_STEP = "end step"
    BEGIN_COMBAT = "beginning of combat"


STEP_EVENTS = frozenset({EventKind.UPKEEP, EventKind.END_STEP,
                         EventKind.BEGIN_COMBAT})
"""Events that happen to a *player*, not to a permanent.

"At the beginning of your upkeep" is watched by everything its controller has on
the battlefield, so these are matched by scanning rather than by looking up the
one object something happened to."""


@dataclass(frozen=True)
class Watch:
    """What a triggered ability is watching for.

    `is_self` is the original family: the permanent's own event. The scoped
    fields are the ChangesZone family — "a land you control enters" (landfall's
    expansion), "another creature you control dies" — where the subject is some
    OTHER permanent, filtered by type, by controller, and by whether the watcher
    itself counts."""

    kind: EventKind
    is_self: bool = True
    subject: str = ""
    """Card type the subject must have: land, creature, artifact, permanent."""
    yours: bool = False
    """The subject's controller must be the watcher's controller."""
    excludes_self: bool = False
    """"Another": the watcher's own event does not count."""


@dataclass(frozen=True)
class Event:
    """Something that happened, which abilities may be watching for."""

    kind: EventKind
    object_id: int | None
    """The permanent it happened to, or None for a step event."""
    controller: int
    """Whose event it is: the permanent's controller, or the active player for a
    step event — which is what makes "your upkeep" mean *yours*."""


# "this creature enters", "this enchantment enters", "cardname enters",
# "this land enters" — the type word varies and carries no meaning for a trigger
# the permanent has about *itself*, so it is matched and discarded.
_SELF_ENTERS = re.compile(
    r"^(?:this|cardname)(?:\s+\w+)?\s+enters(?:\s+the\s+battlefield)?$", re.I)
_SELF_DIES = re.compile(
    r"^(?:this|cardname)(?:\s+\w+)?\s+dies$", re.I)
# "a land you control enters", "another creature you control dies",
# "a creature dies" — a subject that is not the ability's own source.
_SUBJECT = re.compile(
    r"^(?:whenever )?(a|an|another) (land|creature|artifact|permanent)"
    r"( you control)? (enters|dies)(?: the battlefield)?$", re.I)

_SELF_ATTACKS = re.compile(
    r"^(?:this|cardname)(?:\s+\w+)?\s+attacks$", re.I)
_SELF_COMBAT_DAMAGE = re.compile(
    r"^(?:this|cardname)(?:\s+\w+)?\s+deals combat damage to a player$", re.I)

# Step triggers. "your" is load-bearing and is why the event carries a player:
# an upkeep trigger belongs to its controller, not to whoever is watching.
_STEPS = (
    (re.compile(r"^the beginning of your upkeep$", re.I), EventKind.UPKEEP),
    (re.compile(r"^the beginning of your end step$", re.I), EventKind.END_STEP),
    (re.compile(r"^the beginning of combat on your turn$", re.I),
     EventKind.BEGIN_COMBAT),
)


def parse_trigger(text: str) -> Watch | None:
    """The watch this condition describes, or `None` to refuse it.

    `None` is the important return. Every caller treats it as "this card is not
    modelled" and reports it by name, exactly as an unrecognised target phrase
    does — a trigger the engine half-understands is worse than one it declines.
    """
    condition = (text or "").strip().rstrip(".").lower()
    if not condition:
        return None
    if _SELF_ENTERS.match(condition):
        return Watch(EventKind.ENTERS)
    if _SELF_DIES.match(condition):
        return Watch(EventKind.DIES)
    if _SELF_ATTACKS.match(condition):
        return Watch(EventKind.ATTACKS)
    if _SELF_COMBAT_DAMAGE.match(condition):
        return Watch(EventKind.COMBAT_DAMAGE_TO_PLAYER)
    for pattern, kind in _STEPS:
        if pattern.match(condition):
            return Watch(kind, is_self=False)
    scoped = _SUBJECT.match(condition)
    if scoped:
        article, subject, yours, verb = scoped.groups()
        return Watch(
            EventKind.ENTERS if verb == "enters" else EventKind.DIES,
            is_self=False,
            subject=subject,
            yours=bool(yours),
            excludes_self=article == "another",
        )
    return None


def watched_by(card: Card) -> tuple[tuple[Watch, Ability], ...]:
    """Every triggered ability on `card` this engine can honour."""
    out: list[tuple[Watch, Ability]] = []
    for ability in card.abilities:
        if ability.kind != "triggered":
            continue
        watch = parse_trigger(ability.trigger)
        if watch is not None:
            out.append((watch, ability))
    return tuple(out)


def unsupported(card: Card) -> tuple[str, ...]:
    """Trigger conditions on `card` that this engine refuses, by name."""
    return tuple(
        f"trigger not understood: {a.trigger!r}"
        for a in card.abilities
        if a.kind == "triggered" and parse_trigger(a.trigger) is None
    )


def fired_by(card: Card, event: EventKind) -> tuple[Ability, ...]:
    """The self-watching abilities on `card` that `event` sets off."""
    return tuple(ability for watch, ability in watched_by(card)
                 if watch.kind is event and watch.is_self)
