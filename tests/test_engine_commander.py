"""The command zone, the tax, the replacement, and 21 damage.

`cards.formats` already says a Commander deck is 100 singleton cards at 40 life,
and none of that needs the engine. These four rules do — without them a
"Commander game" is a long game of one-ofs.
"""

from __future__ import annotations

from manalab.cards.mana import parse_cost
from manalab.cards.model import Card
from manalab.engine import commander, sba
from manalab.engine.state import GameState
from manalab.engine.zones import Zone

GENERAL = Card("gen", "Yeva, Nature's Herald", parse_cost("{2}{G}{G}"),
               "Legendary Creature — Elf Advisor", power="4", toughness="4")
BEAR = Card("bear", "Grizzly Bears", parse_cost("{1}{G}"), "Creature — Bear",
            power="2", toughness="2")


def table(players: int = 4) -> GameState:
    return GameState.new([[BEAR] * 60 for _ in range(players)], starting_life=40)


def commander_of(state: GameState, player: int) -> object:
    obj = state.create(GENERAL, owner=player, zone=Zone.COMMAND, quiet=True)
    obj.is_commander = True
    return obj


# --- the command zone ----------------------------------------------------


def test_a_commander_starts_in_the_command_zone():
    state = table()
    obj = commander_of(state, 0)
    assert obj.zone is Zone.COMMAND
    assert state.zone(Zone.COMMAND) == [obj]


def test_a_dying_commander_returns_to_the_command_zone():
    """CR 903.9. Removal answers a commander for a turn, not for the game."""
    state = table()
    obj = commander_of(state, 0)
    obj = state.move(obj, Zone.BATTLEFIELD)

    dead = state.move(obj, Zone.GRAVEYARD)

    assert dead.zone is Zone.COMMAND, "the commander went to the graveyard"
    assert state.graveyard(0) == []


def test_exiling_a_commander_also_returns_it():
    state = table()
    obj = state.move(commander_of(state, 0), Zone.BATTLEFIELD)
    exiled = state.move(obj, Zone.EXILE)
    assert exiled.zone is Zone.COMMAND


def test_a_non_commander_dies_normally():
    """The replacement must be about being a commander, not about being legendary
    or about the zone — everything else still goes to the graveyard."""
    state = table()
    bear = state.create(BEAR, owner=0, zone=Zone.BATTLEFIELD, quiet=True)
    dead = state.move(bear, Zone.GRAVEYARD)
    assert dead.zone is Zone.GRAVEYARD
    assert len(state.graveyard(0)) == 1


def test_being_a_commander_survives_a_zone_change():
    """`fresh_copy` drops damage, counters and tapped status by design. If it
    dropped this too, a commander would come back once and never again."""
    state = table()
    obj = state.move(commander_of(state, 0), Zone.BATTLEFIELD)
    assert obj.is_commander
    again = state.move(obj, Zone.GRAVEYARD)
    assert again.is_commander


# --- the tax -------------------------------------------------------------


def test_the_first_cast_is_untaxed():
    state = table()
    obj = commander_of(state, 0)
    assert commander.tax_for(state, 0) == 0
    assert commander.cost_from_command_zone(state, obj).cmc == GENERAL.cost.cmc


def test_each_cast_makes_the_next_two_more():
    """CR 903.8 — what stops a deck recasting its commander every turn forever."""
    state = table()
    obj = commander_of(state, 0)

    commander.note_cast(state, 0)
    assert commander.cost_from_command_zone(state, obj).cmc == GENERAL.cost.cmc + 2

    commander.note_cast(state, 0)
    assert commander.cost_from_command_zone(state, obj).cmc == GENERAL.cost.cmc + 4


def test_the_tax_is_generic_and_leaves_the_pips_alone():
    """A commander does not get harder to *colour* the more it is cast."""
    state = table()
    obj = commander_of(state, 0)
    commander.note_cast(state, 0)
    taxed = commander.cost_from_command_zone(state, obj)
    assert taxed.symbols == GENERAL.cost.symbols
    assert taxed.generic == GENERAL.cost.generic + 2


def test_the_tax_is_per_player():
    state = table()
    mine = commander_of(state, 0)
    theirs = commander_of(state, 1)
    commander.note_cast(state, 0)

    assert commander.cost_from_command_zone(state, mine).cmc > GENERAL.cost.cmc
    assert commander.cost_from_command_zone(state, theirs).cmc == GENERAL.cost.cmc


# --- twenty-one ----------------------------------------------------------


def test_twenty_one_from_one_commander_is_a_loss():
    """CR 903.10a. The reason 40 life is not simply 20 life twice."""
    state = table()
    source = commander_of(state, 0)
    for _ in range(21):
        commander.deal_commander_damage(state, 1, source, 1)

    sba.check(state)

    assert state.players[1].has_lost
    assert state.players[1].loss_reason == "commander damage"
    assert state.players[1].life == 40, "life was never the thing that ran out"


def test_twenty_is_not_enough():
    state = table()
    source = commander_of(state, 0)
    commander.deal_commander_damage(state, 1, source, 20)
    sba.check(state)
    assert not state.players[1].has_lost


def test_damage_from_two_commanders_does_not_pool():
    """Twenty from each is forty, and it is still not a loss. Folding them into
    one total would end the game."""
    state = table()
    first = commander_of(state, 0)
    second = state.create(
        Card("g2", "Azusa, Lost but Seeking", parse_cost("{2}{G}"),
             "Legendary Creature — Human Monk", power="1", toughness="2"),
        owner=2, zone=Zone.COMMAND, quiet=True)
    second.is_commander = True

    commander.deal_commander_damage(state, 1, first, 20)
    commander.deal_commander_damage(state, 1, second, 20)
    sba.check(state)

    assert not state.players[1].has_lost
    assert commander.lethal_commander_damage(state, 1) is None


def test_damage_from_a_creature_that_is_not_a_commander_is_not_tracked():
    state = table()
    bear = state.create(BEAR, owner=0, zone=Zone.BATTLEFIELD, quiet=True)
    commander.deal_commander_damage(state, 1, bear, 21)
    assert state.players[1].commander_damage == {}
