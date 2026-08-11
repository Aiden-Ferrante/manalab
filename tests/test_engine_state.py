"""Engine core: zones, object identity, and the rules that hide in them.

Object identity across zone changes (CR 400.7) and owner-vs-controller routing
(CR 400.3) are the two places where a plausible-looking implementation is
silently wrong, so they get the most attention here.
"""

from __future__ import annotations

import pytest

from manalab.cards.mana import parse_cost
from manalab.cards.model import Card
from manalab.engine import GameObject, GameState, Player, Zone

BEAR = Card("bear", "Grizzly Bears", parse_cost("{1}{G}"), "Creature — Bear",
            power="2", toughness="2")
HASTY = Card("hasty", "Raging Goblin", parse_cost("{R}"), "Creature — Goblin",
             power="1", toughness="1", keywords=frozenset({"Haste"}))
FOREST = Card("forest", "Forest", parse_cost(None), "Basic Land — Forest",
              produces=frozenset("G"), taps_for_mana=True)
TAPLAND = Card("tap", "Blossoming Sands", parse_cost(None), "Land",
               produces=frozenset("GW"), taps_for_mana=True, enters_tapped=True,
               oracle_text="Blossoming Sands enters tapped.")
BOLT = Card("bolt", "Lightning Bolt", parse_cost("{R}"), "Instant")


def make_state(seed: int = 0) -> GameState:
    return GameState.new([[FOREST] * 10 + [BEAR] * 10, [FOREST] * 20], seed=seed)


# --- setup --------------------------------------------------------------


def test_new_game_deals_libraries_to_owners() -> None:
    state = make_state()
    assert len(state.library(0)) == 20
    assert len(state.library(1)) == 20
    assert state.hand(0) == []
    assert all(o.owner == 0 for o in state.library(0))


def test_shuffle_is_seeded() -> None:
    a, b = make_state(7), make_state(7)
    a.shuffle(0)
    b.shuffle(0)
    assert [o.card.name for o in a.library(0)] == [o.card.name for o in b.library(0)]

    c = make_state(8)
    c.shuffle(0)
    assert [o.card.name for o in c.library(0)] != [o.card.name for o in a.library(0)]


# --- object identity ----------------------------------------------------


def test_changing_zones_mints_a_new_object() -> None:
    """CR 400.7. The old id must be gone, so stale references fail loudly
    instead of mutating something that no longer exists."""
    state = make_state()
    card = state.library(0)[0]
    old_id = card.id

    new = state.move(card, Zone.HAND)

    assert new.id != old_id
    assert old_id not in state.objects
    assert new.card is card.card  # same printed card, different object


def test_zone_change_discards_damage_counters_and_tapped_status() -> None:
    state = make_state()
    bear = state.create(BEAR, owner=0, zone=Zone.BATTLEFIELD)
    bear.tapped = True
    bear.damage = 1
    bear.add_counters("+1/+1", 3)

    dead = state.move(bear, Zone.GRAVEYARD)

    assert dead.damage == 0
    assert dead.counters == {}
    assert dead.tapped is False


def test_moving_a_stale_reference_raises() -> None:
    state = make_state()
    card = state.library(0)[0]
    state.move(card, Zone.HAND)
    with pytest.raises(KeyError):
        state.move(card, Zone.GRAVEYARD)


def test_private_zones_route_to_the_owner_not_the_controller() -> None:
    """CR 400.3: a stolen creature dies to its *owner's* graveyard. Routing by
    controller instead silently steals the card."""
    state = make_state()
    stolen = state.create(BEAR, owner=1, zone=Zone.BATTLEFIELD, controller=0)
    assert stolen.controller == 0 and stolen.owner == 1

    dead = state.move(stolen, Zone.GRAVEYARD)

    assert dead.controller == 1
    assert len(state.graveyard(1)) == 1
    assert state.graveyard(0) == []


# --- battlefield entry --------------------------------------------------


def test_permanents_enter_summoning_sick() -> None:
    state = make_state()
    bear = state.move(state.create(BEAR, owner=0, zone=Zone.HAND), Zone.BATTLEFIELD)
    assert bear.summoning_sick
    assert not bear.can_attack


def test_haste_ignores_summoning_sickness() -> None:
    state = make_state()
    goblin = state.move(state.create(HASTY, owner=0, zone=Zone.HAND), Zone.BATTLEFIELD)
    assert goblin.summoning_sick
    assert goblin.can_attack


def test_sickness_does_not_restrain_noncreatures() -> None:
    """A land that just entered still taps for mana; that is why Sol Ring works."""
    state = make_state()
    land = state.move(state.create(FOREST, owner=0, zone=Zone.HAND), Zone.BATTLEFIELD)
    assert land.summoning_sick
    assert land.can_tap


def test_taplands_enter_tapped() -> None:
    state = make_state()
    land = state.move(state.create(TAPLAND, owner=0, zone=Zone.HAND), Zone.BATTLEFIELD)
    assert land.tapped
    assert not land.can_tap


def test_untap_step_clears_tapped_and_sickness_for_one_player_only() -> None:
    state = make_state()
    mine = state.move(state.create(BEAR, owner=0, zone=Zone.HAND), Zone.BATTLEFIELD)
    theirs = state.move(state.create(BEAR, owner=1, zone=Zone.HAND), Zone.BATTLEFIELD)
    mine.tapped = theirs.tapped = True

    state.untap_all(0)

    assert not mine.tapped and not mine.summoning_sick
    assert theirs.tapped and theirs.summoning_sick


# --- drawing ------------------------------------------------------------


def test_draw_takes_from_the_top() -> None:
    state = make_state()
    top = state.library(0)[0].card.name
    (drawn,) = state.draw(0)
    assert drawn.card.name == top
    assert drawn.zone == Zone.HAND
    assert len(state.library(0)) == 19


def test_drawing_from_an_empty_library_flags_rather_than_loses() -> None:
    """CR 704.5b: the loss happens when state-based actions next run, not at the
    moment of the draw. A player who draws out and then wins first has not lost."""
    state = GameState.new([[FOREST], []])
    state.draw(1)
    assert state.players[1].drew_from_empty
    assert not state.players[1].has_lost


# --- characteristics ----------------------------------------------------


def test_counters_modify_power_and_toughness() -> None:
    state = make_state()
    bear = state.create(BEAR, owner=0, zone=Zone.BATTLEFIELD)
    assert (bear.power, bear.toughness) == (2, 2)

    bear.add_counters("+1/+1", 2)
    assert (bear.power, bear.toughness) == (4, 4)

    bear.add_counters("-1/-1", 1)
    assert (bear.power, bear.toughness) == (3, 3)


def test_counters_are_removed_when_they_reach_zero() -> None:
    state = make_state()
    bear = state.create(BEAR, owner=0, zone=Zone.BATTLEFIELD)
    bear.add_counters("+1/+1", 1)
    bear.add_counters("+1/+1", -1)
    assert bear.counters == {}


def test_lethal_damage_accounts_for_counters() -> None:
    state = make_state()
    bear = state.create(BEAR, owner=0, zone=Zone.BATTLEFIELD)
    bear.damage = 2
    assert bear.lethal_damage

    bear.add_counters("+1/+1", 1)
    assert not bear.lethal_damage


# --- cloning ------------------------------------------------------------


def test_clone_is_independent() -> None:
    state = make_state()
    bear = state.create(BEAR, owner=0, zone=Zone.BATTLEFIELD)

    copy = state.clone()
    copy.objects[bear.id].tapped = True
    copy.players[0].life = 5
    copy.draw(0)

    assert not state.objects[bear.id].tapped
    assert state.players[0].life == 20
    assert len(state.hand(0)) == 0


def test_clone_preserves_the_random_stream() -> None:
    """Lookahead must not consume the real game's randomness, but must see the
    same shuffles it would have seen."""
    a = make_state(3)
    b = a.clone()
    a.shuffle(0)
    b.shuffle(0)
    assert [o.card.name for o in a.library(0)] == [o.card.name for o in b.library(0)]
