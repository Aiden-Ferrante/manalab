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

Not yet recognised, in rough order of what would pay next: upkeep and end-step
triggers (1,185), attack triggers (855), combat-damage-to-a-player (420), and
the "another permanent you control" family, which needs an event to carry a
subject distinct from the ability's source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from manalab.cards.model import Ability, Card


class EventKind(Enum):
    ENTERS = "enters"
    DIES = "dies"


@dataclass(frozen=True)
class Event:
    """Something that happened, which abilities may be watching for."""

    kind: EventKind
    object_id: int
    """The permanent it happened to."""
    controller: int


# "this creature enters", "this enchantment enters", "cardname enters",
# "this land enters" — the type word varies and carries no meaning for a trigger
# the permanent has about *itself*, so it is matched and discarded.
_SELF_ENTERS = re.compile(
    r"^(?:this|cardname)(?:\s+\w+)?\s+enters(?:\s+the\s+battlefield)?$", re.I)
_SELF_DIES = re.compile(
    r"^(?:this|cardname)(?:\s+\w+)?\s+dies$", re.I)


def parse_trigger(text: str) -> EventKind | None:
    """The event this condition fires on, or `None` to refuse it.

    `None` is the important return. Every caller treats it as "this card is not
    modelled" and reports it by name, exactly as an unrecognised target phrase
    does — a trigger the engine half-understands is worse than one it declines.
    """
    condition = (text or "").strip().rstrip(".").lower()
    if not condition:
        return None
    if _SELF_ENTERS.match(condition):
        return EventKind.ENTERS
    if _SELF_DIES.match(condition):
        return EventKind.DIES
    return None


def watched_by(card: Card) -> tuple[tuple[EventKind, Ability], ...]:
    """Every triggered ability on `card` this engine can honour."""
    out: list[tuple[EventKind, Ability]] = []
    for ability in card.abilities:
        if ability.kind != "triggered":
            continue
        kind = parse_trigger(ability.trigger)
        if kind is not None:
            out.append((kind, ability))
    return tuple(out)


def unsupported(card: Card) -> tuple[str, ...]:
    """Trigger conditions on `card` that this engine refuses, by name."""
    return tuple(
        f"trigger not understood: {a.trigger!r}"
        for a in card.abilities
        if a.kind == "triggered" and parse_trigger(a.trigger) is None
    )


def fired_by(card: Card, event: EventKind) -> tuple[Ability, ...]:
    """The abilities on `card` that `event` sets off."""
    return tuple(ability for kind, ability in watched_by(card) if kind is event)
