"""Continuous effects from static abilities — the one layer combat can see.

The property that matters here is that contributions are *recomputed*, not
accumulated. An anthem leaving the battlefield has to stop applying without
anything remembering that it did, which is precisely what an `obj.power += 1`
on resolution can never give you.
"""

from __future__ import annotations

from manalab.cards.mana import parse_cost
from manalab.cards.model import Ability, Card, Effect
from manalab.engine import fidelity, sba, statics
from manalab.engine.state import GameState
from manalab.engine.zones import Zone

BEAR = Card("bear", "Grizzly Bears", parse_cost("{1}{G}"), "Creature — Bear",
            power="2", toughness="2")


def anthem(amount: str = "+1/+1") -> Card:
    text = f"Creatures you control get {amount}."
    ability = Ability(kind="static", text=text,
                      effects=(Effect("pump", (("amount", amount),
                                               ("target", "Creatures you control"))),))
    return Card("an", "Anthem", parse_cost("{1}{W}"), "Enchantment",
                oracle_text=text, abilities=(ability,))


def self_buff(amount: str = "+2/+2") -> Card:
    text = f"This creature gets {amount}."
    ability = Ability(kind="static", text=text,
                      effects=(Effect("pump", (("amount", amount),
                                               ("target", "This creature"))),))
    return Card("sb", "Big Bear", parse_cost("{2}{G}"), "Creature — Bear",
                power="2", toughness="2", oracle_text=text, abilities=(ability,))


def board(*cards, owner: int = 0) -> GameState:
    state = GameState.new([[], []])
    for card in cards:
        state.create(card, owner=owner, zone=Zone.BATTLEFIELD, quiet=True)
    return state


def test_an_anthem_buffs_your_creatures():
    state = board(anthem(), BEAR)
    statics.apply(state)
    bear = next(o for o in state.battlefield(0) if o.card.name == "Grizzly Bears")
    assert (bear.power, bear.toughness) == (3, 3)


def test_an_anthem_does_not_buff_the_opponents_creatures():
    state = board(anthem())
    state.create(BEAR, owner=1, zone=Zone.BATTLEFIELD, quiet=True)
    statics.apply(state)
    theirs = next(o for o in state.battlefield(1))
    assert (theirs.power, theirs.toughness) == (2, 2)


def test_an_anthem_leaving_stops_applying():
    """The whole reason this is a recompute rather than an increment."""
    state = board(anthem(), BEAR)
    statics.apply(state)
    bear = next(o for o in state.battlefield(0) if o.card.name == "Grizzly Bears")
    assert bear.power == 3

    lord = next(o for o in state.battlefield(0) if o.card.name == "Anthem")
    state.move(lord, Zone.GRAVEYARD)
    statics.apply(state)

    assert bear.power == 2, "the anthem's buff outlived the anthem"


def test_applying_twice_changes_nothing():
    """Idempotent by construction. If it were not, every priority pass would
    make the board a little bigger."""
    state = board(anthem(), BEAR)
    statics.apply(state)
    statics.apply(state)
    statics.apply(state)
    bear = next(o for o in state.battlefield(0) if o.card.name == "Grizzly Bears")
    assert (bear.power, bear.toughness) == (3, 3)


def test_two_anthems_stack():
    state = board(anthem(), anthem(), BEAR)
    statics.apply(state)
    bear = next(o for o in state.battlefield(0) if o.card.name == "Grizzly Bears")
    assert (bear.power, bear.toughness) == (4, 4)


def test_a_self_buff_applies_only_to_itself():
    state = board(self_buff(), BEAR)
    statics.apply(state)
    big = next(o for o in state.battlefield(0) if o.card.name == "Big Bear")
    plain = next(o for o in state.battlefield(0) if o.card.name == "Grizzly Bears")
    assert (big.power, big.toughness) == (4, 4)
    assert (plain.power, plain.toughness) == (2, 2)


def test_a_negative_anthem_can_kill():
    """An anthem leaving or arriving changes what state-based actions see, which
    is why statics are recomputed before SBAs rather than after."""
    state = board(anthem("-2/-2"), BEAR)
    statics.apply(state)
    sba.check(state)
    assert not [o for o in state.battlefield(0) if o.card.name == "Grizzly Bears"]


def test_a_conditional_static_is_refused_whole():
    """"as long as you control a Forest" is a condition this cannot evaluate, and
    applying the buff unconditionally is a strictly better card than the one
    printed."""
    text = "This creature gets +2/+2 as long as you control a Forest."
    card = Card("c", "Conditional", parse_cost("{1}{G}"), "Creature — Bear",
                power="2", toughness="2", oracle_text=text,
                abilities=(Ability(kind="static", text=text,
                                   effects=(Effect("pump", (("amount", "+2/+2"),
                                                            ("target", "This creature"))),)),))
    assert statics.applicable(card) == ()
    assert any("condition" in r for r in statics.unsupported(card))
    assert not fidelity.assess(card).faithful


def test_an_attachment_buff_is_refused():
    """"Enchanted creature gets +2/+2" is the biggest static family (825 of
    2,121) and needs aura mechanics the engine does not have."""
    text = "Enchanted creature gets +2/+2."
    card = Card("a", "Aura", parse_cost("{1}{W}"), "Enchantment — Aura",
                oracle_text=text,
                abilities=(Ability(kind="static", text=text,
                                   effects=(Effect("pump", (("amount", "+2/+2"),
                                                            ("target", "Enchanted creature"))),)),))
    assert any("cannot resolve" in r for r in statics.unsupported(card))


def test_a_static_the_engine_applies_makes_its_card_faithful():
    assert fidelity.assess(self_buff()).faithful, fidelity.assess(self_buff()).reasons
