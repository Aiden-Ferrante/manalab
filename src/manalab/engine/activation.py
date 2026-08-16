"""Activated abilities: their costs, and which ones this engine can pay.

`{T}: Add {G}` and `{2}, {T}: Draw a card` are the shape of 8,585 abilities on
7,063 cards, and the engine had no action for any of them — the whole vocabulary
was pass, play a land, cast a spell, attack, block. Equipment, sacrifice outlets,
tap abilities and planeswalkers were all unreachable.

Costs are `mana, {T}` in the overwhelming majority: `{T}` alone is 2,407 of them,
and the top fourteen shapes are all some combination of a mana cost and a tap.
Those are parsed here. Costs that sacrifice, discard, exile or pay life are
refused — 2,008 activated costs carry a real action, and paying one by ignoring
it would make the ability free.

Mana abilities are deliberately not offered as actions. `{T}: Add {G}` is already
how `engine.mana` pays for things, by tapping sources at payment time; offering
it as a separate activation would let the same land be tapped twice in a way the
payment planner cannot see.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from manalab.cards.mana import ManaCost, parse_cost
from manalab.cards.model import Ability, Card

_TAP = re.compile(r"^\{t\}$", re.I)
_MANA = re.compile(r"^(?:\{[^}]+\})+$")


@dataclass(frozen=True)
class ActivationCost:
    mana: ManaCost
    taps: bool = False


def parse_activation_cost(text: str) -> ActivationCost | None:
    """`"{2}, {T}"` -> a cost, or `None` to refuse it.

    Refusing is the default. A cost this cannot read is a cost the engine would
    otherwise pay by ignoring, which turns "sacrifice a creature: draw a card"
    into "draw a card".
    """
    raw = (text or "").strip()
    if not raw:
        return None

    mana_parts: list[str] = []
    taps = False
    for part in (p.strip() for p in raw.split(",")):
        if not part:
            continue
        if _TAP.match(part):
            if taps:
                return None      # two taps is not a cost this understands
            taps = True
        elif _MANA.match(part):
            mana_parts.append(part)
        else:
            return None          # sacrifice, discard, exile, pay N life
    if not mana_parts and not taps:
        return None

    cost = parse_cost("".join(mana_parts)) if mana_parts else parse_cost(None)
    if cost.approximated:
        return None              # a lossy cost is one we would undercharge
    return ActivationCost(cost, taps)


def is_mana_ability(ability: Ability) -> bool:
    """Whether this ability only makes mana.

    Those are already how `engine.mana` pays for things — it taps sources at
    payment time — so offering one as a separate action would let the same
    permanent be tapped twice without the payment planner seeing it.
    """
    return bool(ability.effects) and all(e.verb == "add_mana" for e in ability.effects)


def activatable(card: Card) -> tuple[tuple[int, Ability, ActivationCost], ...]:
    """Abilities of `card` this engine can activate, with where they are printed."""
    out: list[tuple[int, Ability, ActivationCost]] = []
    for index, ability in enumerate(card.abilities):
        if ability.kind != "activated" or is_mana_ability(ability):
            continue
        cost = parse_activation_cost(ability.cost)
        if cost is not None:
            out.append((index, ability, cost))
    return tuple(out)


def unsupported(card: Card) -> tuple[str, ...]:
    """Activated abilities this engine cannot pay for, by name."""
    return tuple(
        f"activation cost not understood: {a.cost!r}"
        for a in card.abilities
        if a.kind == "activated" and not is_mana_ability(a)
        and parse_activation_cost(a.cost) is None
    )
