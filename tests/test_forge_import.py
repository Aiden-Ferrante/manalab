"""Reading Forge's encoding instead of parsing English.

These use hand-written Forge scripts rather than the checkout, so they run
without `data/forge` present — the same rule `test_forge.py` follows.
"""

from __future__ import annotations

import manalab.cards.forge as forge
from manalab.cards import forge_import as FI
from manalab.cards.mana import parse_cost
from manalab.cards.model import Card

BOLT = """\
Name:Lightning Bolt
ManaCost:R
Types:Instant
A:SP$ DealDamage | ValidTgts$ Any | NumDmg$ 3
Oracle:Lightning Bolt deals 3 damage to any target.
"""

VISIONARY = """\
Name:Elvish Visionary
ManaCost:1 G
Types:Creature Elf Shaman
PT:1/1
T:Mode$ ChangesZone | Origin$ Any | Destination$ Battlefield | ValidCard$ Card.Self | Execute$ TrigDraw | TriggerDescription$ When CARDNAME enters, draw a card.
SVar:TrigDraw:DB$ Draw | Defined$ You | NumCards$ 1
Oracle:When Elvish Visionary enters, draw a card.
"""

GRAVEDIGGER = """\
Name:Odd Thing
ManaCost:2 B
Types:Creature Zombie
PT:2/2
T:Mode$ ChangesZone | Origin$ Battlefield | Destination$ Graveyard | ValidCard$ Card.Self | Execute$ TrigMill | TriggerDescription$ When CARDNAME dies, mill a card.
SVar:TrigMill:DB$ Mill | Defined$ You | NumCards$ 1
Oracle:When Odd Thing dies, mill a card.
"""


def oracle_of(*scripts: str) -> dict[str, forge.ForgeCard]:
    out: dict[str, forge.ForgeCard] = {}
    for script in scripts:
        for card in forge.parse_script(script):
            out[forge.slug(card.name)] = card
    return out


def card(name: str) -> Card:
    return Card(name.lower(), name, parse_cost("{1}"), "Creature — Elf")


def test_a_spell_translates_with_its_target_and_amount():
    imported = FI.with_forge_effects(card("Lightning Bolt"), oracle_of(BOLT))
    (effect,) = imported.effects
    assert effect.verb == "deal_damage"
    assert effect.get("amount") == 3
    assert effect.get("target") == "any target"


def test_a_trigger_translates_through_its_execute_pointer():
    """A `T:` line is a condition; its effect hangs off `Execute$`, not
    `SubAbility$`. Following only SubAbility left every triggered ability with no
    effects at all."""
    imported = FI.with_forge_effects(card("Elvish Visionary"), oracle_of(VISIONARY))
    (ability,) = imported.abilities
    assert ability.kind == "triggered"
    assert [e.verb for e in ability.effects] == ["draw"]
    assert ability.trigger == "this creature enters", \
        "without a condition the engine can read, the trigger could never fire"


def test_a_dies_trigger_is_recognised_from_its_zones():
    imported = FI.with_forge_effects(card("Odd Thing"), oracle_of(GRAVEDIGGER))
    (ability,) = imported.abilities
    assert ability.trigger == "this creature dies"


def test_defined_you_is_the_controller_and_not_a_target():
    """`Defined$ You` names something the effect already knows about. Treating it
    as an unmappable target discarded every ability that had one."""
    imported = FI.with_forge_effects(card("Elvish Visionary"), oracle_of(VISIONARY))
    (effect,) = imported.effects
    assert effect.get("target") is None


def test_an_effect_forge_encodes_that_we_cannot_map_lands_in_unparsed():
    """Never silently dropped — the same contract the English parser keeps, so
    `fidelity` refuses the card rather than executing half of it."""
    imported = FI.with_forge_effects(card("Odd Thing"), oracle_of(GRAVEDIGGER))
    assert imported.unparsed, "Mill is unmapped and should have been recorded"
    assert "Mill" in " ".join(imported.unparsed)


def test_a_card_forge_does_not_have_is_returned_unchanged():
    original = card("Not In Forge")
    assert FI.with_forge_effects(original, oracle_of(BOLT)) is original


# --- choosing between the two sources ------------------------------------


def test_the_fallback_never_scores_below_the_parser_alone():
    """Monotone by construction: keep what already works, reach for Forge only
    where we have nothing.

    The obvious rule — prefer Forge wherever it translates completely — was
    measured at 468 against the parser's 540. A complete translation is not a
    complete card.
    """
    from manalab.evaluate.pool import best_effects

    playable = Card("b", "Lightning Bolt", parse_cost("{R}"), "Instant",
                    oracle_text="Lightning Bolt deals 3 damage to any target.")
    from manalab.cards.effects import with_effects
    playable = with_effects(playable)

    chosen = best_effects(playable, oracle_of(BOLT))
    assert chosen is playable, "a card we can already play was swapped out"


def test_forge_is_used_when_our_parse_cannot_play_the_card():
    from manalab.evaluate.pool import best_effects

    # No abilities at all on our side, and text we never read.
    unplayable = Card("u", "Lightning Bolt", parse_cost("{R}"), "Instant",
                      oracle_text="Lightning Bolt deals 3 damage to any target.")
    chosen = best_effects(unplayable, oracle_of(BOLT))
    assert chosen is not unplayable
    assert [e.verb for e in chosen.effects] == ["deal_damage"]
