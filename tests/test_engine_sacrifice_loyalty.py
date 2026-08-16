"""Sacrifice as a choice the engine makes, and loyalty as a payable cost."""

from __future__ import annotations

from manalab.cards.mana import parse_cost
from manalab.cards.model import Ability, Card, Effect
from manalab.engine import actions as A
from manalab.engine import resolve, sba
from manalab.engine.agents import PassingAgent
from manalab.engine.game import Game
from manalab.engine.state import GameState
from manalab.engine.steps import Step
from manalab.engine.zones import Zone

FOREST = Card("f", "Forest", parse_cost(None), "Basic Land — Forest",
              produces=frozenset("G"), taps_for_mana=True, oracle_text="")
BEAR = Card("b", "Grizzly Bears", parse_cost("{1}{G}"), "Creature — Bear",
            power="2", toughness="2")
ELF = Card("e", "Llanowar Elves", parse_cost("{G}"), "Creature — Elf",
           power="1", toughness="1")


def game(cards=()):
    state = GameState.new([[FOREST] * 40, [FOREST] * 40])
    for c in cards:
        o = state.create(c, owner=0, zone=Zone.BATTLEFIELD, quiet=True)
        o.summoning_sick = False
    return state, Game(state, [PassingAgent(), PassingAgent()])


def test_sacrifice_a_creature_takes_the_weakest():
    """The declared choice rule: weakest matching permanent, oldest first —
    deterministic, so common random numbers survive."""
    state, _ = game([BEAR, ELF])
    spell = state.create(
        Card("s", "Bloodfeast", parse_cost("{B}"), "Sorcery",
             effects=(Effect("sacrifice", (("what", "a creature"),)),)),
        owner=0, zone=Zone.STACK)
    resolve.apply(state, spell, [], state.log)
    names = [o.card.name for o in state.battlefield(0) if o.is_creature]
    assert names == ["Grizzly Bears"], "the 1/1 should have been chosen"


def test_sacrificing_fires_dies_triggers():
    state, game_ = game([ELF])
    spell = state.create(
        Card("s", "Edict", parse_cost("{B}"), "Sorcery",
             effects=(Effect("sacrifice", (("what", "a creature"),)),)),
        owner=0, zone=Zone.STACK)
    state.events.clear()
    resolve.apply(state, spell, [], state.log)
    from manalab.engine.triggers import EventKind
    assert any(e.kind is EventKind.DIES for e in state.events)


def test_self_sacrifice_cost_pays_and_the_ability_still_resolves():
    """Sakura-Tribe Elder's shape: the cost kills the source, the ability
    resolves anyway — costs are paid on activation."""
    text = "Sacrifice this creature: Draw a card."
    sac = Card("sc", "Sac Drawer", parse_cost("{1}"), "Creature — Elf",
               power="1", toughness="1", oracle_text=text,
               abilities=(Ability(kind="activated", text=text,
                                  cost="Sacrifice this creature",
                                  effects=(Effect("draw", (("amount", 1),)),)),))
    state, game_ = game([sac])
    action = next(o for o in A.legal(state, 0, Step.PRECOMBAT_MAIN, stack_empty=True)
                  if isinstance(o, A.ActivateAbility))
    game_._apply(0, action)
    assert not [o for o in state.battlefield(0) if o.is_creature], "cost unpaid"
    game_._resolve_top()
    assert len(state.hand(0)) == 1, "the ability died with its source"


def walker(cost="+1", body="Draw a card.") -> Card:
    text = f"{cost}: {body}"
    return Card("pw", "Test Walker", parse_cost("{2}"),
                "Legendary Planeswalker — Test", loyalty="3", oracle_text=text,
                abilities=(Ability(kind="activated", text=text,
                                   cost=f"{cost} loyalty",
                                   effects=(Effect("draw", (("amount", 1),)),)),))


def test_a_planeswalker_enters_with_its_printed_loyalty():
    state, _ = game()
    obj = state.create(walker(), owner=0, zone=Zone.BATTLEFIELD)
    assert obj.counters.get("loyalty") == 3


def test_a_loyalty_ability_pays_in_counters_and_is_once_per_turn():
    state, game_ = game()
    obj = state.create(walker("+1"), owner=0, zone=Zone.BATTLEFIELD, quiet=True)
    obj.counters["loyalty"] = 3
    action = next(o for o in A.legal(state, 0, Step.PRECOMBAT_MAIN, stack_empty=True)
                  if isinstance(o, A.ActivateAbility))
    game_._apply(0, action)
    assert obj.counters["loyalty"] == 4
    assert obj.loyalty_used
    again = [o for o in A.legal(state, 0, Step.PRECOMBAT_MAIN, stack_empty=True)
             if isinstance(o, A.ActivateAbility)]
    assert not again, "CR 606.3: one loyalty ability per walker per turn"


def test_a_minus_ability_needs_the_counters():
    state, _ = game()
    obj = state.create(walker("-7"), owner=0, zone=Zone.BATTLEFIELD, quiet=True)
    obj.counters["loyalty"] = 3
    offered = [o for o in A.legal(state, 0, Step.PRECOMBAT_MAIN, stack_empty=True)
               if isinstance(o, A.ActivateAbility)]
    assert not offered, "cannot remove 7 loyalty from 3 (CR 606.5)"


def test_paying_to_zero_kills_the_walker():
    state, game_ = game()
    obj = state.create(walker("-3"), owner=0, zone=Zone.BATTLEFIELD, quiet=True)
    obj.counters["loyalty"] = 3
    action = next(o for o in A.legal(state, 0, Step.PRECOMBAT_MAIN, stack_empty=True)
                  if isinstance(o, A.ActivateAbility))
    game_._apply(0, action)
    sba.check(state)
    assert not [o for o in state.battlefield(0) if "Planeswalker" in o.types]


def test_loyalty_is_sorcery_speed_only():
    state, _ = game()
    obj = state.create(walker("+1"), owner=0, zone=Zone.BATTLEFIELD, quiet=True)
    obj.counters["loyalty"] = 3
    offered = [o for o in A.legal(state, 0, Step.END, stack_empty=True)
               if isinstance(o, A.ActivateAbility)]
    assert not offered


def test_sakura_tribe_elder_is_faithful_for_real():
    from manalab.cards.store import CardStore
    from manalab.engine import fidelity

    elder = CardStore().by_name("Sakura-Tribe Elder")
    assert fidelity.assess(elder).faithful, fidelity.assess(elder).reasons
