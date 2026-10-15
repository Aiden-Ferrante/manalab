"""Activated abilities: paying for them, using them, and refusing the rest.

The whole action vocabulary was pass, play a land, cast a spell, attack, block —
8,585 abilities on 7,063 cards had no way to be used at all. Equipment, sacrifice
outlets, tap abilities and planeswalkers were unreachable.
"""

from __future__ import annotations

import pytest

from manalab.cards.mana import parse_cost
from manalab.cards.model import Ability, Card, Effect
from manalab.engine import actions as A
from manalab.engine import activation, fidelity
from manalab.engine.agents import CurveAgent, PassingAgent
from manalab.engine.game import Game
from manalab.engine.state import GameState
from manalab.engine.steps import Step
from manalab.engine.zones import Zone

FOREST = Card("forest", "Forest", parse_cost(None), "Basic Land — Forest",
              produces=frozenset("G"), taps_for_mana=True, oracle_text="")


def tapper(cost: str = "{T}") -> Card:
    text = f"{cost}: Draw a card."
    return Card("tp", "Card Tapper", parse_cost("{1}{G}"), "Creature — Elf",
                power="1", toughness="1", oracle_text=text,
                abilities=(Ability(kind="activated", text=text, cost=cost,
                                   effects=(Effect("draw", (("amount", 1),)),)),))


# --- reading costs -------------------------------------------------------


@pytest.mark.parametrize("cost,taps,cmc", [
    ("{T}", True, 0),
    ("{1}, {T}", True, 1),
    ("{2}, {T}", True, 2),
    ("{1}", False, 1),
    ("{R}", False, 1),
    ("{1}{R}", False, 2),
])
def test_mana_and_tap_costs_are_read(cost, taps, cmc):
    parsed = activation.parse_activation_cost(cost)
    assert parsed is not None, cost
    assert parsed.taps is taps
    assert parsed.mana.cmc == cmc


@pytest.mark.parametrize("cost", [
    "Sacrifice a creature",
    "{1}, Sacrifice a Food",
    "Discard a card",
    "{T}, Exile a card from your graveyard",
    "Pay 3 life",
    "",
])
def test_a_cost_with_a_real_action_is_refused(cost):
    """2,008 activated costs carry an action. Paying one by ignoring it turns
    "sacrifice a creature: draw a card" into "draw a card"."""
    assert activation.parse_activation_cost(cost) is None


def test_a_mana_ability_is_not_offered_as_an_action():
    """`{T}: Add {G}` is already how `engine.mana` pays for things. Offering it
    separately would let the same land be tapped twice without the payment
    planner seeing it."""
    land = Card("l", "Forest-ish", parse_cost(None), "Land",
                oracle_text="{T}: Add {G}.",
                abilities=(Ability(kind="activated", text="{T}: Add {G}.", cost="{T}",
                                   effects=(Effect("add_mana", (("mana", "{G}"),)),)),))
    assert activation.activatable(land) == ()
    assert activation.unsupported(land) == ()


# --- using them ----------------------------------------------------------


def board(card: Card, lands: int = 3) -> tuple[GameState, Game]:
    state = GameState.new([[FOREST] * 40, [FOREST] * 40])
    obj = state.create(card, owner=0, zone=Zone.BATTLEFIELD, quiet=True)
    obj.summoning_sick = False
    for _ in range(lands):
        state.create(FOREST, owner=0, zone=Zone.BATTLEFIELD, quiet=True)
    return state, Game(state, [PassingAgent(), PassingAgent()])


def test_an_activation_is_offered():
    state, _ = board(tapper())
    options = A.legal(state, 0, Step.PRECOMBAT_MAIN, stack_empty=True)
    assert [o for o in options if isinstance(o, A.ActivateAbility)]


def test_activating_taps_the_permanent_and_resolves_the_effect():
    state, game = board(tapper())
    action = next(o for o in A.legal(state, 0, Step.PRECOMBAT_MAIN, stack_empty=True)
                  if isinstance(o, A.ActivateAbility))

    game._apply(0, action)
    source = state.objects[action.object_id]
    assert source.tapped, "the {T} in the cost was not paid"

    game._resolve_top()
    assert len(state.hand(0)) == 1


def test_the_permanent_stays_when_its_ability_resolves():
    """An activated ability is its own object. Resolving it must not move the
    permanent that made it."""
    state, game = board(tapper())
    action = next(o for o in A.legal(state, 0, Step.PRECOMBAT_MAIN, stack_empty=True)
                  if isinstance(o, A.ActivateAbility))
    game._apply(0, action)
    game._resolve_top()

    assert [o.card.name for o in state.battlefield(0) if not o.is_land] == ["Card Tapper"]
    assert state.graveyard(0) == []


def test_a_tapped_permanent_cannot_pay_a_tap_cost_again():
    state, _ = board(tapper())
    source = next(o for o in state.battlefield(0) if not o.is_land)
    source.tapped = True

    options = A.legal(state, 0, Step.PRECOMBAT_MAIN, stack_empty=True)
    assert not [o for o in options if isinstance(o, A.ActivateAbility)]


def test_a_summoning_sick_creature_cannot_pay_a_tap_cost():
    state = GameState.new([[FOREST] * 40, [FOREST] * 40])
    state.create(tapper(), owner=0, zone=Zone.BATTLEFIELD, quiet=True)   # sick
    options = A.legal(state, 0, Step.PRECOMBAT_MAIN, stack_empty=True)
    assert not [o for o in options if isinstance(o, A.ActivateAbility)]


def test_mana_is_actually_paid():
    state, game = board(tapper("{2}, {T}"))
    action = next(o for o in A.legal(state, 0, Step.PRECOMBAT_MAIN, stack_empty=True)
                  if isinstance(o, A.ActivateAbility))
    game._apply(0, action)

    tapped_lands = [o for o in state.battlefield(0) if o.is_land and o.tapped]
    assert len(tapped_lands) == 2


def test_an_ability_that_cannot_be_paid_for_is_not_offered():
    state, _ = board(tapper("{7}, {T}"), lands=2)
    options = A.legal(state, 0, Step.PRECOMBAT_MAIN, stack_empty=True)
    assert not [o for o in options if isinstance(o, A.ActivateAbility)]


# --- the pilot -----------------------------------------------------------


def test_the_agent_uses_a_helpful_ability():
    state, _ = board(tapper())
    options = A.legal(state, 0, Step.PRECOMBAT_MAIN, stack_empty=True)
    choice = CurveAgent().act(state, 0, options)
    assert isinstance(choice, A.ActivateAbility)


def test_the_agent_declines_to_point_removal_at_itself():
    """The pilot is crude, but not so crude that it shoots its own board — that
    is a broken instrument rather than an interestingly bad play."""
    text = "{T}: Card Shooter deals 2 damage to target creature."
    shooter = Card("sh", "Card Shooter", parse_cost("{1}{R}"), "Creature — Elf",
                   power="1", toughness="1", oracle_text=text,
                   abilities=(Ability(kind="activated", text=text, cost="{T}",
                                      effects=(Effect("deal_damage",
                                                      (("amount", 2),
                                                       ("target", "target creature"))),)),))
    state, _ = board(shooter)
    friend = state.create(FOREST, owner=0, zone=Zone.BATTLEFIELD, quiet=True)
    options = A.legal(state, 0, Step.PRECOMBAT_MAIN, stack_empty=True)
    activations = [o for o in options if isinstance(o, A.ActivateAbility)]

    if activations:      # only own creatures on board -> every target is ours
        choice = CurveAgent().act(state, 0, options)
        assert not isinstance(choice, A.ActivateAbility), \
            "the pilot shot its own creature"


# --- fidelity ------------------------------------------------------------


def test_a_card_whose_ability_we_can_use_is_faithful():
    assert fidelity.assess(tapper()).faithful, fidelity.assess(tapper()).reasons


def test_a_card_whose_cost_we_cannot_pay_is_refused():
    text = "Sacrifice a creature: Draw a card."
    card = Card("s", "Sac Outlet", parse_cost("{1}{B}"), "Creature — Zombie",
                power="1", toughness="1", oracle_text=text,
                abilities=(Ability(kind="activated", text=text,
                                   cost="Sacrifice a creature",
                                   effects=(Effect("draw", (("amount", 1),)),)),))
    report = fidelity.assess(card)
    assert not report.faithful
    assert any("activation cost not understood" in r for r in report.reasons)


def test_flash_counts_as_implemented_because_it_is() -> None:
    """`actions.legal` offers a creature with flash at instant speed, so refusing
    the card for an "unimplemented keyword" was a stale refusal.

    It is kept out of COMBAT_KEYWORDS on purpose: a test asserts every entry
    there is read by `combat` or `objects`, and flash is read by neither.
    """
    from manalab.engine.objects import COMBAT_KEYWORDS, IMPLEMENTED_KEYWORDS

    assert "flash" in IMPLEMENTED_KEYWORDS
    assert "flash" not in COMBAT_KEYWORDS

    card = Card("f", "Flashy", parse_cost("{1}{G}"), "Creature — Elf",
                power="2", toughness="2", oracle_text="Flash",
                keywords=frozenset({"Flash"}))
    assert fidelity.assess(card).faithful, fidelity.assess(card).reasons
