"""Triggered abilities: recognition, firing, and the refusal boundary.

The engine had no notion of an event before this, so a creature with an
enters-the-battlefield trigger resolved onto the battlefield and did nothing,
silently. These tests are mostly about the two halves of that: the trigger
happens, and a trigger the engine does not understand keeps its card out of the
pool rather than being ignored.
"""

from __future__ import annotations

import pytest

from manalab.cards.mana import parse_cost
from manalab.cards.model import Ability, Card, Effect
from manalab.engine import fidelity, triggers
from manalab.engine.agents import PassingAgent
from manalab.engine.game import Game
from manalab.engine.state import GameState
from manalab.engine.triggers import EventKind
from manalab.engine.zones import Zone

FOREST = Card("forest", "Forest", parse_cost(None), "Basic Land — Forest",
              produces=frozenset("G"), taps_for_mana=True, oracle_text="")


def visionary() -> Card:
    """A 1/1 that draws a card when it enters — the commonest shape in Magic."""
    draw = Ability(kind="triggered", text="When this creature enters, draw a card.",
                   effects=(Effect("draw", (("amount", 1),)),),
                   trigger="this creature enters")
    return Card("ev", "Elvish Visionary", parse_cost("{1}{G}"),
                "Creature — Elf Shaman", power="1", toughness="1",
                oracle_text="When this creature enters, draw a card.",
                abilities=(draw,), effects=draw.effects)


def death_drawer() -> Card:
    dies = Ability(kind="triggered", text="When this creature dies, draw a card.",
                   effects=(Effect("draw", (("amount", 1),)),),
                   trigger="this creature dies")
    return Card("dd", "Death Drawer", parse_cost("{1}{B}"),
                "Creature — Zombie", power="1", toughness="1",
                oracle_text="When this creature dies, draw a card.",
                abilities=(dies,), effects=dies.effects)


def game_with(library_size: int = 10) -> tuple[GameState, Game]:
    state = GameState.new([[FOREST] * library_size, [FOREST] * library_size])
    return state, Game(state, [PassingAgent(), PassingAgent()])


# --- recognising conditions ---------------------------------------------


@pytest.mark.parametrize("condition", [
    "this creature enters", "CARDNAME enters", "this enchantment enters",
    "this land enters", "this artifact enters", "This creature enters.",
])
def test_the_self_enters_family_is_recognised(condition):
    assert triggers.parse_trigger(condition) is EventKind.ENTERS


@pytest.mark.parametrize("condition", ["this creature dies", "CARDNAME dies"])
def test_the_self_dies_family_is_recognised(condition):
    assert triggers.parse_trigger(condition) is EventKind.DIES


@pytest.mark.parametrize("condition", [
    "a land you control enters",          # someone else's event, not its own
    "another creature you control dies",  # needs a subject distinct from the source
    "you cast a noncreature spell",       # happens on the stack, not the battlefield
    "the beginning of each opponent's upkeep",
    "",
])
def test_everything_else_is_refused_rather_than_guessed(condition):
    """A trigger half-understood is worse than one declined — the same contract
    `targets` keeps for phrases it does not know."""
    assert triggers.parse_trigger(condition) is None


def test_an_unrecognised_trigger_makes_its_card_unfaithful():
    text = "Whenever a land you control enters, draw a card."
    landfall = Ability(kind="triggered", text=text,
                       effects=(Effect("draw", (("amount", 1),)),),
                       trigger="a land you control enters")
    card = Card("u", "Landfaller", parse_cost("{1}{G}"), "Creature — Elf",
                power="1", toughness="1", abilities=(landfall,),
                oracle_text=text)
    report = fidelity.assess(card)
    assert not report.faithful
    assert any("trigger not understood" in r for r in report.reasons)


def test_a_card_whose_trigger_is_executed_is_faithful():
    assert fidelity.assess(visionary()).faithful, fidelity.assess(visionary()).reasons


# --- firing --------------------------------------------------------------


def test_entering_the_battlefield_fires_the_trigger():
    state, game = game_with()
    state.create(visionary(), owner=0, zone=Zone.BATTLEFIELD)

    game._collect_triggers()
    stack = state.zone(Zone.STACK)
    assert len(stack) == 1
    assert stack[0].trigger is not None, "the stack entry is the ability, not the card"

    game._resolve_top()
    assert len(state.hand(0)) == 1, "the trigger did not draw"


def test_the_permanent_stays_when_its_trigger_resolves():
    """A triggered ability is its own object (CR 113.7a). Resolving it must not
    move the permanent, nor put a second copy of the card in a graveyard."""
    state, game = game_with()
    state.create(visionary(), owner=0, zone=Zone.BATTLEFIELD)
    game._collect_triggers()
    game._resolve_top()

    assert [o.card.name for o in state.battlefield(0)] == ["Elvish Visionary"]
    assert state.graveyard(0) == []
    assert state.zone(Zone.STACK) == []


def test_dying_fires_a_dies_trigger():
    state, game = game_with()
    obj = state.create(death_drawer(), owner=0, zone=Zone.BATTLEFIELD, quiet=True)
    state.move(obj, Zone.GRAVEYARD)

    game._collect_triggers()
    assert len(state.zone(Zone.STACK)) == 1
    game._resolve_top()
    assert len(state.hand(0)) == 1


def test_a_trigger_belongs_to_the_controller_not_the_active_player():
    state, game = game_with()
    state.create(visionary(), owner=1, zone=Zone.BATTLEFIELD)
    game._collect_triggers()
    game._resolve_top()

    assert len(state.hand(1)) == 1
    assert len(state.hand(0)) == 0, "the wrong player drew"


def test_quiet_creation_does_not_fire_a_trigger():
    """Building a board position in a fixture is not a game event."""
    state, game = game_with()
    state.create(visionary(), owner=0, zone=Zone.BATTLEFIELD, quiet=True)
    game._collect_triggers()
    assert state.zone(Zone.STACK) == []


def test_a_vanilla_creature_fires_nothing():
    bear = Card("b", "Grizzly Bears", parse_cost("{1}{G}"), "Creature — Bear",
                power="2", toughness="2")
    state, game = game_with()
    state.create(bear, owner=0, zone=Zone.BATTLEFIELD)
    game._collect_triggers()
    assert state.zone(Zone.STACK) == []


def test_two_copies_each_fire_their_own_trigger():
    state, game = game_with()
    state.create(visionary(), owner=0, zone=Zone.BATTLEFIELD)
    state.create(visionary(), owner=0, zone=Zone.BATTLEFIELD)

    game._collect_triggers()
    assert len(state.zone(Zone.STACK)) == 2
    game._resolve_top()
    game._resolve_top()
    assert len(state.hand(0)) == 2


# --- tokens enter, and entering is an event ------------------------------


def test_a_created_token_is_a_real_permanent():
    from manalab.cards.model import Effect
    from manalab.engine import resolve

    state, _ = game_with()
    maker = state.create(
        Card("m", "Soldier Maker", parse_cost("{1}{W}"), "Sorcery",
             effects=(Effect("create_token", (("amount", 2),
                                              ("what", "1/1 white Soldier creature"))),)),
        owner=0, zone=Zone.STACK)

    resolve.apply(state, maker, [], state.log)

    tokens = [o for o in state.battlefield(0)]
    assert len(tokens) == 2
    assert (tokens[0].power, tokens[0].toughness) == (1, 1)
    assert tokens[0].card.name == "Soldier"


def test_a_token_entering_fires_enters_triggers():
    """A token entering triggers exactly as a cast creature does — which is why
    tokens are made through `state.create` rather than inserted directly."""
    from manalab.cards.model import Effect
    from manalab.engine import resolve

    state, game = game_with()
    state.create(visionary(), owner=0, zone=Zone.BATTLEFIELD, quiet=True)
    state.events.clear()

    maker = state.create(
        Card("m", "Maker", parse_cost("{1}{G}"), "Sorcery",
             effects=(Effect("create_token", (("amount", 1),
                                              ("what", "1/1 green Saproling creature"))),)),
        owner=0, zone=Zone.STACK)
    resolve.apply(state, maker, [], state.log)

    assert any(e.kind is EventKind.ENTERS for e in state.events), \
        "a token entering the battlefield is an event like any other"


# --- step and combat triggers -------------------------------------------


@pytest.mark.parametrize("condition,kind", [
    ("this creature attacks", EventKind.ATTACKS),
    ("CARDNAME attacks", EventKind.ATTACKS),
    ("this creature deals combat damage to a player",
     EventKind.COMBAT_DAMAGE_TO_PLAYER),
    ("the beginning of your upkeep", EventKind.UPKEEP),
    ("the beginning of your end step", EventKind.END_STEP),
    ("the beginning of combat on your turn", EventKind.BEGIN_COMBAT),
])
def test_the_step_and_combat_families_are_recognised(condition, kind):
    assert triggers.parse_trigger(condition) is kind


def upkeeper() -> Card:
    text = "At the beginning of your upkeep, draw a card."
    ability = Ability(kind="triggered", text=text,
                      effects=(Effect("draw", (("amount", 1),)),),
                      trigger="the beginning of your upkeep")
    return Card("up", "Upkeeper", parse_cost("{1}{G}"), "Creature — Elf",
                power="1", toughness="1", oracle_text=text, abilities=(ability,))


def test_an_upkeep_trigger_belongs_to_its_controller():
    """"Your upkeep" is the whole reason a step event carries a player: it fires
    on its controller's turn, not on everyone's."""
    from manalab.engine.steps import Step

    state, game = game_with()
    state.create(upkeeper(), owner=1, zone=Zone.BATTLEFIELD, quiet=True)

    state.active_player = 0
    game._turn_based_action(Step.UPKEEP)
    game._collect_triggers()
    assert state.zone(Zone.STACK) == [], "P1's upkeep trigger fired on P0's turn"

    state.active_player = 1
    game._turn_based_action(Step.UPKEEP)
    game._collect_triggers()
    assert len(state.zone(Zone.STACK)) == 1


def test_a_step_trigger_fires_for_every_matching_permanent():
    from manalab.engine.steps import Step

    state, game = game_with()
    state.create(upkeeper(), owner=0, zone=Zone.BATTLEFIELD, quiet=True)
    state.create(upkeeper(), owner=0, zone=Zone.BATTLEFIELD, quiet=True)

    state.active_player = 0
    game._turn_based_action(Step.UPKEEP)
    game._collect_triggers()

    assert len(state.zone(Zone.STACK)) == 2


def test_attacking_fires_an_attack_trigger():
    attacker_card = Card(
        "at", "Raider", parse_cost("{1}{R}"), "Creature — Human",
        power="2", toughness="2",
        oracle_text="Whenever this creature attacks, draw a card.",
        abilities=(Ability(kind="triggered",
                           text="Whenever this creature attacks, draw a card.",
                           effects=(Effect("draw", (("amount", 1),)),),
                           trigger="this creature attacks"),))
    state, game = game_with()
    obj = state.create(attacker_card, owner=0, zone=Zone.BATTLEFIELD, quiet=True)
    obj.summoning_sick = False
    state.active_player = 0

    game._apply_attack_for_test = None
    from manalab.engine import actions as A
    game.agents[0] = type("Fixed", (), {
        "name": "fixed",
        "act": lambda self, s, p, options: next(
            o for o in options if isinstance(o, A.DeclareAttackers) and o.attackers),
    })()
    game._declare_attackers()

    game._collect_triggers()
    assert len(state.zone(Zone.STACK)) == 1
    game._resolve_top()
    assert len(state.hand(0)) == 1
