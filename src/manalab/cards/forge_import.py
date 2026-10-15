"""Read Forge's encoding of a card instead of parsing its English.

`effects.py` reads oracle text with regexes. That works, and the 2026-08-15
audit measured exactly how well: on the mono-green Commander pool, 2,984 cards
carry text it could not classify at all — across **1,284 distinct shapes**, the
largest being 8.3% of them. A long tail like that has no feature to implement.
It is per-card work, and per-card work is what Forge already did: 33,664 scripts
maintained by people who execute them in a rules engine.

Measured before writing any of this: of those 2,984 cards, **2,976 have a Forge
script and 569 are encoded using only effects this engine already executes.**
Those clear with no new rules work at all — the engine could always play them
and only our parsing stood in the way.

**Optional by design.** This is a *backend*, not a replacement. `effects.py`
remains the default and manalab works with no Forge checkout present; turning
this on is a deliberate act. Two reasons, and the second is the important one:

  * Forge's encoding is engine-idiomatic rather than a neutral logical form, so
    it should be possible to compare the two rather than being locked to one.
  * Forge is GPL-3.0. The scripts live in gitignored `data/`, fetched on demand,
    exactly like the Scryfall corpus — nothing derived is ever committed. Reading
    them locally is not distribution. A *published* manalab that could not
    function without them would be a different question, and keeping the parser
    as the default is what stops that question being answered by accident.
    See ADR 0008.
"""

from __future__ import annotations

import re
from dataclasses import replace

import manalab.cards.forge as forge
from manalab.cards.model import Ability, Card, Effect

# Forge's verb -> ours, for the effects `engine.resolve` executes. Anything not
# here is left as an unmatched clause, so a card using it stays refused rather
# than arriving half-understood.
VERBS = {
    "DealDamage": "deal_damage",
    "Destroy": "destroy",
    "Draw": "draw",
    "GainLife": "gain_life",
    "Pump": "pump",
    "Counter": "counter_spell",
    "PutCounter": "put_counters",
    "Token": "create_token",
    "Mana": "add_mana",
}

# Forge's target vocabulary -> the phrases `engine.targets` recognises.
TARGETS = {
    "Any": "any target",
    "Creature": "target creature",
    "Creature.YouCtrl": "target creature you control",
    "Player": "target player",
    "Opponent": "target opponent",
}

_PT = re.compile(r"^[+-]?\d+$")


def _amount(raw: str | None, default: int = 1) -> int | None:
    try:
        return int(str(raw).lstrip("+")) if raw is not None else default
    except (TypeError, ValueError):
        return None          # X, or a count we do not model


def _effect(ability: forge.ForgeAbility) -> Effect | None:
    """One Forge ability -> one of our effects, or None to leave it unmatched."""
    verb = VERBS.get(ability.verb)
    if verb is None:
        return None

    params: list[tuple[str, str | int]] = []

    # `ValidTgts` is a chosen target. `Defined` is not — it names something the
    # effect already knows about, and `You`/`Self` mean the controller and the
    # source, which is exactly what our effects do when given no target at all.
    # Treating `Defined$ You` as an unmappable target discarded every ability
    # that had one, which is most of them: it is how the first cut of this scored
    # 288 against the English parser's 540.
    defined = ability.get("Defined")
    if defined and defined not in ("You", "Self"):
        return None
    valid = ability.get("ValidTgts")
    if valid:
        phrase = TARGETS.get(valid)
        if phrase is None:
            return None      # a restriction we cannot enforce; refuse the card
        params.append(("target", phrase))

    if verb == "pump":
        power, toughness = ability.get("NumAtt", "0"), ability.get("NumDef", "0")
        if not (_PT.match(str(power)) and _PT.match(str(toughness))):
            return None
        params.append(("amount", f"{int(str(power).lstrip('+')):+}/"
                                 f"{int(str(toughness).lstrip('+')):+}"))
    elif verb == "deal_damage":
        if ability.get("DividedAsYouChoose"):
            return None      # one number on our side, several on theirs
        amount = _amount(ability.get("NumDmg"))
        if amount is None:
            return None
        params.append(("amount", amount))
    elif verb in ("draw", "gain_life", "put_counters", "create_token"):
        key = {"draw": "NumCards", "gain_life": "LifeAmount",
               "put_counters": "CounterNum", "create_token": "TokenAmount"}[verb]
        amount = _amount(ability.get(key))
        if amount is None:
            return None
        params.append(("amount", amount))
        if verb == "put_counters":
            params.append(("kind", str(ability.get("CounterType", "P1P1"))
                           .replace("P1P1", "+1/+1").replace("M1M1", "-1/-1")))
        if verb == "create_token":
            described = ability.get("TokenScript") or ability.get("TokenImage") or ""
            if not described:
                return None
            params.append(("what", described.replace("_", " ")))
    elif verb == "add_mana":
        produced = ability.get("Produced")
        if not produced or len(produced) != 1:
            return None
        params.append(("mana", "{" + produced + "}"))

    return Effect(verb, tuple(params))


def abilities_for(card: Card, oracle: dict[str, forge.ForgeCard]) -> tuple[Ability, ...] | None:
    """Forge's encoding of `card` as our `Ability` tuple, or None if absent.

    An ability Forge encodes with something we do not map lands in `unparsed`,
    which is the same contract the English parser keeps: never silently dropped,
    so `fidelity` refuses the card rather than executing half of it.
    """
    ref = oracle.get(forge.slug(card.name))
    if ref is None:
        return None

    out: list[Ability] = []
    by_name = dict(ref.svars)
    for entry in ref.abilities:
        # A `T:` line is a *condition*; its effect hangs off `Execute$`, not
        # `SubAbility$`. Following only SubAbility left every triggered ability
        # with no effects at all — which is how the first cut of this scored 288
        # against the English parser's 540.
        chain: list[forge.ForgeAbility] = []
        if entry.kind == "A":
            chain.append(entry)
        nxt = entry.get("Execute") or entry.get("SubAbility")
        while nxt and nxt in by_name:
            sub = forge._ability("A", by_name[nxt])   # noqa: SLF001
            if sub is None:
                break
            chain.append(sub)
            nxt = sub.get("SubAbility")

        effects: list[Effect] = []
        unparsed: list[str] = []
        for link in chain:
            translated = _effect(link)
            if translated is None:
                unparsed.append(f"{link.mode or link.kind}${link.verb}")
            else:
                effects.append(translated)
        if not chain:
            unparsed.append(f"{entry.kind}${entry.verb}")

        kind = {"A": "spell" if entry.mode == "SP" else "activated",
                "T": "triggered", "R": "static", "S": "static"}.get(entry.kind, "spell")
        out.append(Ability(kind=kind,
                           text=entry.get("TriggerDescription")
                           or entry.get("SpellDescription") or entry.verb,
                           effects=tuple(effects), unparsed=tuple(unparsed),
                           trigger=_trigger_phrase(entry) if kind == "triggered" else ""))
    return tuple(out)


def _trigger_phrase(entry: forge.ForgeAbility) -> str:
    """Forge's trigger condition, in the words `engine.triggers` recognises.

    Returns "" for anything else, which leaves the ability with no condition and
    so keeps its card out of the pool — the same refusal the English path makes.
    """
    if entry.verb != "ChangesZone" or entry.get("ValidCard") != "Card.Self":
        return ""
    origin, destination = entry.get("Origin"), entry.get("Destination")
    if destination == "Battlefield":
        return "this creature enters"
    if destination == "Graveyard" and origin == "Battlefield":
        return "this creature dies"
    return ""


def with_forge_effects(card: Card, oracle: dict[str, forge.ForgeCard]) -> Card:
    """`card` carrying Forge's encoding rather than our parse of its English.

    Falls back to the card unchanged when Forge has no script for it, so a
    caller can apply this across a whole corpus without branching.
    """
    abilities = abilities_for(card, oracle)
    if abilities is None:
        return card
    return replace(
        card,
        abilities=abilities,
        effects=tuple(e for a in abilities for e in a.effects),
        unparsed=tuple(u for a in abilities for u in a.unparsed),
    )
