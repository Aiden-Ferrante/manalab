"""Seedborn Muse and Nykthos: the first turn-structure hook, and the first
hand-coded card. Every registry entry must earn a test like these."""

from __future__ import annotations

import pytest

from manalab.cards.mana import parse_cost
from manalab.cards.model import Card
from manalab.cards.store import CardStore
from manalab.engine import fidelity, resolve
from manalab.engine.agents import PassingAgent
from manalab.engine.game import Game
from manalab.engine.state import GameState
from manalab.engine.steps import Step
from manalab.engine.zones import Zone

FOREST = Card("f", "Forest", parse_cost(None), "Basic Land — Forest",
              produces=frozenset("G"), taps_for_mana=True, oracle_text="")


def store():
    return CardStore()


@pytest.mark.usefixtures("cards_db")
def test_seedborn_untaps_you_on_the_opponents_turn():
    s = store()
    state = GameState.new([[FOREST] * 40, [FOREST] * 40])
    game = Game(state, [PassingAgent(), PassingAgent()])
    muse = state.create(s.by_name("Seedborn Muse"), owner=0,
                        zone=Zone.BATTLEFIELD, quiet=True)
    land = state.create(FOREST, owner=0, zone=Zone.BATTLEFIELD, quiet=True)
    land.tapped = True

    state.active_player = 1                     # the OPPONENT's untap step
    game._turn_based_action(Step.UNTAP)
    assert not land.tapped, "Seedborn's controller should untap too"


def test_without_the_muse_you_stay_tapped():
    state = GameState.new([[FOREST] * 40, [FOREST] * 40])
    game = Game(state, [PassingAgent(), PassingAgent()])
    land = state.create(FOREST, owner=0, zone=Zone.BATTLEFIELD, quiet=True)
    land.tapped = True
    state.active_player = 1
    game._turn_based_action(Step.UNTAP)
    assert land.tapped, "untap leaked without the static"


@pytest.mark.usefixtures("cards_db")
def test_the_effect_leaves_with_its_source():
    s = store()
    state = GameState.new([[FOREST] * 40, [FOREST] * 40])
    game = Game(state, [PassingAgent(), PassingAgent()])
    muse = state.create(s.by_name("Seedborn Muse"), owner=0,
                        zone=Zone.BATTLEFIELD, quiet=True)
    land = state.create(FOREST, owner=0, zone=Zone.BATTLEFIELD, quiet=True)
    state.move(muse, Zone.GRAVEYARD)
    land.tapped = True
    state.active_player = 1
    game._turn_based_action(Step.UNTAP)
    assert land.tapped, "a dead Muse kept untapping — asked of the board, not cached"


@pytest.mark.usefixtures("cards_db")
def test_nykthos_adds_devotion_mana_to_the_pool():
    s = store()
    state = GameState.new([[], []])
    # Two Grizzly Bears: {1}{G} each -> devotion to green 2.
    for _ in range(2):
        state.create(s.by_name("Grizzly Bears"), owner=0,
                     zone=Zone.BATTLEFIELD, quiet=True)
    nykthos = s.by_name("Nykthos, Shrine to Nyx")
    entry = state.create(nykthos, owner=0, zone=Zone.STACK, controller=0)
    ability = nykthos.abilities[1]
    resolve.apply_effects(state, entry, ability.effects, (), state.log)

    assert state.players[0].mana_pool == {"G": 2}


@pytest.mark.usefixtures("cards_db")
def test_nykthos_with_no_devotion_adds_nothing():
    s = store()
    state = GameState.new([[], []])
    nykthos = s.by_name("Nykthos, Shrine to Nyx")
    entry = state.create(nykthos, owner=0, zone=Zone.STACK, controller=0)
    resolve.apply_effects(state, entry, nykthos.abilities[1].effects, (), state.log)
    assert state.players[0].mana_pool == {}


@pytest.mark.usefixtures("cards_db")
def test_both_are_faithful_from_the_store():
    s = store()
    for name in ("Seedborn Muse", "Nykthos, Shrine to Nyx"):
        report = fidelity.assess(s.by_name(name))
        assert report.faithful, (name, report.reasons)
