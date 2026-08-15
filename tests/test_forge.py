"""Forge script parsing.

Every fixture here is the verbatim text of a real Forge script, so a change in
their format shows up as a test failure rather than as a silently emptier oracle.
Nothing in this file touches `data/forge` — the parser must be testable without
the checkout, or the tests only run on a machine that already fetched it.
"""

from __future__ import annotations

from manalab.cards import forge

BOLT = """\
Name:Lightning Bolt
ManaCost:R
Types:Instant
A:SP$ DealDamage | ValidTgts$ Any | NumDmg$ 3 | SpellDescription$ CARDNAME deals 3 damage to any target.
Oracle:Lightning Bolt deals 3 damage to any target.
"""

NAMELESS_INVERSION = """\
Name:Nameless Inversion
ManaCost:1 B
Types:Kindred Instant Shapeshifter
K:Changeling
A:SP$ Pump | ValidTgts$ Creature | NumAtt$ +3 | NumDef$ -3 | IsCurse$ True | SubAbility$ DBAnimate | SpellDescription$ Target creature gets +3/-3.
SVar:DBAnimate:DB$ Animate | Defined$ Targeted | Types$ Creature | RemoveCreatureTypes$ True
Oracle:Target creature gets +3/-3 and loses all creature types until end of turn.
"""

FIRE_ICE = """\
Name:Fire
ManaCost:1 R
Types:Instant
A:SP$ DealDamage | ValidTgts$ Any | NumDmg$ 2 | DividedAsYouChoose$ 2
AlternateMode:Split
Oracle:Fire deals 2 damage divided as you choose among one or two targets.

ALTERNATE

Name:Ice
ManaCost:1 U
Types:Instant
A:SP$ Tap | ValidTgts$ Permanent | SubAbility$ DBDraw
SVar:DBDraw:DB$ Draw
Oracle:Tap target permanent.\\nDraw a card.
"""


def test_parses_the_simple_case():
    (card,) = forge.parse_script(BOLT)
    assert card.name == "Lightning Bolt"
    assert card.mana_cost == "R"
    assert card.types == "Instant"
    (ability,) = card.abilities
    assert (ability.mode, ability.verb) == ("SP", "DealDamage")
    assert ability.get("NumDmg") == "3"
    assert ability.get("ValidTgts") == "Any"


def test_pump_keeps_power_and_toughness_apart():
    """The whole reason this oracle exists: +3/-3 is two numbers, not one.

    A representation that collapses them cannot tell a removal spell from a buff,
    which is the defect this corpus is here to catch.
    """
    (card,) = forge.parse_script(NAMELESS_INVERSION)
    pump = next(a for a in card.abilities if a.verb == "Pump")
    assert pump.get("NumAtt") == "+3"
    assert pump.get("NumDef") == "-3"


def test_effect_chain_follows_sub_abilities():
    """Reading only the first ability loses every rider a card carries."""
    (card,) = forge.parse_script(NAMELESS_INVERSION)
    assert [a.verb for a in card.abilities] == ["Pump"]
    assert [a.verb for a in card.effect_chain()] == ["Pump", "Animate"]


def test_keywords_are_collected():
    (card,) = forge.parse_script(NAMELESS_INVERSION)
    assert card.keywords == ("Changeling",)


def test_alternate_blocks_are_separate_cards():
    fire, ice = forge.parse_script(FIRE_ICE)
    assert (fire.name, ice.name) == ("Fire", "Ice")
    assert fire.abilities[0].get("DividedAsYouChoose") == "2"
    assert [a.verb for a in ice.effect_chain()] == ["Tap", "Draw"]


def test_slug_deletes_apostrophes_rather_than_separating_on_them():
    """Getting this wrong loses ~6% of the corpus to phantom misses."""
    assert forge.slug("Saheeli's Artistry") == "saheelis_artistry"
    assert forge.slug("Fire // Ice") == "fire_ice"
    assert forge.slug("Greta, Sweettooth Scourge") == "greta_sweettooth_scourge"
    assert forge.slug("Ajani, Caller of the Pride") == "ajani_caller_of_the_pride"


def test_triggered_and_replacement_lines_are_kept():
    """`T:` and `R:` lead with `Mode$`, not a verb. They are categories our own
    `Effect` cannot express, so the parser records them rather than dropping
    them — an ability we cannot shape is still evidence the card has one."""
    script = (
        "Name:Test Trigger\n"
        "ManaCost:1 W\n"
        "Types:Creature Human\n"
        "PT:1/1\n"
        "T:Mode$ ChangesZone | Origin$ Any | Destination$ Battlefield | Execute$ TrigDraw\n"
        "R:Event$ DamageDone | Prevent$ True | ReplacementResult$ Prevented\n"
        "SVar:TrigDraw:DB$ Draw | NumCards$ 1\n"
        "Oracle:When this creature enters, draw a card.\n"
    )
    (card,) = forge.parse_script(script)
    kinds = {a.kind for a in card.abilities}
    assert kinds == {"T", "R"}
    trigger = next(a for a in card.abilities if a.kind == "T")
    assert trigger.verb == "ChangesZone"
    assert trigger.get("Execute") == "TrigDraw"


def test_malformed_lines_do_not_crash_the_parser():
    """Upstream is a 34k-file hand-maintained corpus; a stray line must cost one
    ability, never the run."""
    script = (
        "Name:Odd\n"
        "ManaCost:R\n"
        "Types:Instant\n"
        "A:SP$ DealDamage | NumDmg$ 1 | |  | Broken\n"
        "this line has no colon at all\n"
        "Oracle:x\n"
    )
    (card,) = forge.parse_script(script)
    assert card.abilities[0].get("NumDmg") == "1"


def test_a_script_with_no_name_is_not_a_card():
    assert forge.parse_script("Types:Instant\nOracle:nothing\n") == ()
