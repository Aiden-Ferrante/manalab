"""Continuous effects from static abilities — a cut-down layer system.

CR 613 applies continuous effects in seven layers with timestamps and
dependencies, and this is not that. It is the one layer that changes what
combat sees: 7c, power and toughness modification from a static ability.

The shape of the problem, counted over the corpus rather than guessed at. Of
2,121 static `pump` effects: 326 buff the permanent itself ("this creature gets
+1/+1"), 825 buff an attached permanent ("enchanted creature", "equipped
creature") and 54 are anthems ("creatures you control get +1/+1"). The
attachment family is the biggest and needs aura and equipment mechanics this
engine does not have, so it is refused; the other two are implemented here.

**Recomputed, never accumulated.** `apply` zeroes every static contribution and
rebuilds it from what is on the battlefield right now. An anthem that leaves
therefore stops applying without anything having to remember it did, which is
the property a layer system exists to provide — and the one an
`obj.power += 1` on resolution could never have.

Conditional statics are refused whole. "This creature gets +2/+2 as long as you
control a Forest" is a condition this has no way to evaluate, and a static that
applied its buff unconditionally would be a strictly better card than the one
printed.
"""

from __future__ import annotations

import re

from manalab.cards.model import Card
from manalab.engine.objects import COMBAT_KEYWORDS, GameObject
from manalab.engine.state import GameState
from manalab.engine.zones import Zone

UNTAP_DURING_OTHERS = (
    "untap all permanents you control during each other player's untap step")
"""Seedborn Muse's line, recognised verbatim. Not a P/T layer effect — it hooks
the untap step itself, which `game._turn_based_action` asks about."""


def untaps_during_others(card: Card) -> bool:
    return any(
        a.kind == "static"
        and a.text.strip().rstrip(".").lower() == UNTAP_DURING_OTHERS
        for a in card.abilities)


def special_texts(card: Card) -> frozenset[str]:
    """Static lines honoured outside the P/T recompute, for fidelity's skip."""
    return frozenset(
        a.text.strip().lower() for a in card.abilities
        if a.kind == "static"
        and a.text.strip().rstrip(".").lower() == UNTAP_DURING_OTHERS)


_SELF = frozenset({"this creature", "this permanent", "cardname", "it"})
_YOUR_CREATURES = frozenset({"creatures you control", "other creatures you control"})

_CONDITIONAL = re.compile(r"\b(as long as|if |whenever|unless|for each)\b", re.I)
_PT = re.compile(r"^([+-]\d+)/([+-]\d+)$")


def _scope(target: str) -> str | None:
    """Who a static ability applies to, or None if the engine cannot tell."""
    cleaned = (target or "").strip().rstrip(".").lower()
    if cleaned in _SELF:
        return "self"
    if cleaned in _YOUR_CREATURES:
        return "your creatures"
    return None


def applicable(card: Card) -> tuple[tuple[str, int, int], ...]:
    """The static P/T effects this engine can apply, as (scope, power, toughness).

    Empty for a card with no static abilities *and* for one whose statics it
    cannot honour — `unsupported` is what tells those two apart.
    """
    out: list[tuple[str, int, int]] = []
    for ability in card.abilities:
        if ability.kind != "static" or _CONDITIONAL.search(ability.text or ""):
            continue
        for effect in ability.effects:
            if effect.verb != "pump":
                continue
            scope = _scope(str(effect.get("target", "")))
            match = _PT.match(str(effect.get("amount", "")).strip())
            if scope and match:
                out.append((scope, int(match.group(1)), int(match.group(2))))
    return tuple(out)


def unsupported(card: Card) -> tuple[str, ...]:
    """Static abilities on `card` this engine cannot apply, by name."""
    reasons: list[str] = []
    for ability in card.abilities:
        if ability.kind != "static":
            continue
        if _CONDITIONAL.search(ability.text or ""):
            reasons.append("static ability with a condition the engine cannot check")
            continue
        for effect in ability.effects:
            if effect.verb == "pump" and _scope(str(effect.get("target", ""))) is None:
                reasons.append(
                    f"static ability applies to {effect.get('target')!r}, which the "
                    "engine cannot resolve")
    return tuple(dict.fromkeys(reasons))


def apply(state: GameState) -> None:
    """Recompute every static P/T contribution on the battlefield.

    Idempotent by construction: the contributions are zeroed and rebuilt, so
    calling this twice in a row changes nothing and an anthem leaving the board
    stops applying immediately.
    """
    battlefield = state.zone(Zone.BATTLEFIELD)
    for obj in battlefield:
        obj.static_power = 0
        obj.static_toughness = 0

    for source in battlefield:
        for scope, power, toughness in applicable(source.card):
            if scope == "self":
                targets = [source]
            else:
                targets = [o for o in battlefield
                           if o.controller == source.controller and o.is_creature
                           and o.id != source.id]
            for obj in targets:
                obj.static_power += power
                obj.static_toughness += toughness
