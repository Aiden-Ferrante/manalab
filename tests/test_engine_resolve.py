"""Spells that do something: targeting, resolution, and refusing the rest.

Real cards from the store where the point is that the *parser* and the engine
agree, synthetic cards where the point is a rule. A test that Lightning Bolt
deals 3 is worth little if `deal_damage` was hand-fed; it is worth a lot if the
amount came out of the oracle text.
"""

from __future__ import annotations

import pytest

from manalab.cards.mana import parse_cost
from manalab.cards.model import Card, Effect
from manalab.cards.store import CardStore
from manalab.engine import actions as A
from manalab.engine import resolve
from manalab.engine import sba
from manalab.engine import targets as T
from manalab.engine.agents import CurveAgent, PassingAgent
from manalab.engine.game import Game
from manalab.engine.state import GameState
from manalab.engine.steps import Step
from manalab.engine.zones import Zone


@pytest.fixture(scope="module")
def store(cards_db) -> CardStore:
    return CardStore()


BEAR = Card("bear", "Bear", parse_cost("{1}{G}"), "Creature — Bear",
            power="2", toughness="2")
GIANT = Card("giant", "Giant", parse_cost("{4}{G}"), "Creature — Giant",
             power="5", toughness="5")
MOUNTAIN = Card("mtn", "Mountain", parse_cost(None), "Basic Land — Mountain",
                produces=frozenset("R"), taps_for_mana=True)


def board(*, hand=(), battlefield=(), opponent=()) -> GameState:
    state = GameState.new([[], []], seed=0)
    state.active_player = 0
    for card in hand:
        state.create(card, owner=0, zone=Zone.HAND)
    for card in battlefield:
        state.create(card, owner=0, zone=Zone.BATTLEFIELD)
    for card in opponent:
        state.create(card, owner=1, zone=Zone.BATTLEFIELD, controller=1)
    return state


def cast_and_resolve(state, card, targets_chosen=()):
    """Put a spell on the stack with targets and resolve it."""
    spell = state.create(card, owner=0, zone=Zone.STACK)
    log: list[str] = []
    resolve.apply(state, spell, targets_chosen, log)
    return log


# --- the target language ------------------------------------------------


def test_understood_phrases_parse() -> None:
    assert T.parse("any target").kind is T.TargetKind.ANY
    assert T.parse("target creature").kind is T.TargetKind.CREATURE
    assert T.parse("Target creature").kind is T.TargetKind.CREATURE
    assert T.parse(None) == T.NO_TARGET


def test_unknown_phrases_are_refused_not_guessed() -> None:
    """The whole safety property. A guess here makes illegal plays look legal."""
    for phrase in ["target nonblack creature", "target creature an opponent controls",
                   "target attacking or blocking creature", "creatures you control"]:
        assert T.parse(phrase) is None, f"{phrase!r} was silently accepted"


def test_mass_scopes_are_understood_but_are_not_targets() -> None:
    """"Destroy all creatures" chooses nothing (CR 115.10)."""
    spec = T.parse("all creatures")
    assert spec is not None
    assert spec.is_mass
    assert not spec.needs_target, "a sweeper must not enumerate targets"


def test_only_your_own_creatures_are_legal_for_you_control() -> None:
    state = board(battlefield=[BEAR], opponent=[GIANT])
    spec = T.TargetSpec(T.TargetKind.CREATURE_YOU_CONTROL)
    chosen = T.legal_targets(state, 0, spec)
    assert len(chosen) == 1
    assert state.objects[chosen[0].object_id].card.name == "Bear"


def test_any_target_covers_creatures_and_players() -> None:
    state = board(battlefield=[BEAR], opponent=[GIANT])
    chosen = T.legal_targets(state, 0, T.TargetSpec(T.TargetKind.ANY))
    assert sum(1 for t in chosen if t.is_player) == 2
    assert sum(1 for t in chosen if not t.is_player) == 2


def test_a_target_that_left_the_battlefield_is_no_longer_legal() -> None:
    """CR 608.2b — the check that makes removal-in-response work."""
    state = board(opponent=[GIANT])
    victim = state.battlefield(1)[0]
    target = T.Target(object_id=victim.id)
    spec = T.TargetSpec(T.TargetKind.CREATURE)

    assert T.still_legal(state, 0, spec, target)
    state.move(victim, Zone.GRAVEYARD)
    assert not T.still_legal(state, 0, spec, target)


# --- real cards, parsed from oracle text --------------------------------


def test_lightning_bolt_deals_three(store) -> None:
    bolt = store.by_name("Lightning Bolt")
    assert not resolve.unsupported(bolt), resolve.unsupported(bolt)

    state = board(opponent=[GIANT])
    cast_and_resolve(state, bolt, (T.Target(player=1),))
    assert state.players[1].life == 17


def test_lightning_bolt_kills_a_small_creature(store) -> None:
    state = board(opponent=[BEAR])
    victim = state.battlefield(1)[0]
    cast_and_resolve(state, store.by_name("Lightning Bolt"),
                     (T.Target(object_id=victim.id),))
    sba.check(state)
    assert state.battlefield(1) == []


def test_lightning_bolt_does_not_kill_a_big_one(store) -> None:
    state = board(opponent=[GIANT])
    victim = state.battlefield(1)[0]
    cast_and_resolve(state, store.by_name("Lightning Bolt"),
                     (T.Target(object_id=victim.id),))
    sba.check(state)
    assert len(state.battlefield(1)) == 1
    assert state.battlefield(1)[0].damage == 3


def test_murder_destroys_regardless_of_size(store) -> None:
    state = board(opponent=[GIANT])
    victim = state.battlefield(1)[0]
    cast_and_resolve(state, store.by_name("Murder"), (T.Target(object_id=victim.id),))
    assert state.battlefield(1) == []


def test_divination_draws_two(store) -> None:
    state = board()
    for _ in range(5):
        state.create(BEAR, owner=0, zone=Zone.LIBRARY)
    before = len(state.hand(0))
    cast_and_resolve(state, store.by_name("Divination"))
    assert len(state.hand(0)) == before + 2


def test_giant_growth_pumps_its_target(store) -> None:
    state = board(battlefield=[BEAR])
    friend = state.battlefield(0)[0]
    cast_and_resolve(state, store.by_name("Giant Growth"),
                     (T.Target(object_id=friend.id),))
    assert friend.power == 5 and friend.toughness == 5


def test_a_pumped_creature_survives_what_would_have_killed_it(store) -> None:
    state = board(battlefield=[BEAR])
    friend = state.battlefield(0)[0]
    friend.damage = 2
    cast_and_resolve(state, store.by_name("Giant Growth"),
                     (T.Target(object_id=friend.id),))
    sba.check(state)
    assert state.battlefield(0), "the pump did not save it"


# --- refusing what it cannot do -----------------------------------------


def test_an_unimplemented_verb_is_refused_by_name(store) -> None:
    reasons = resolve.unsupported(store.by_name("Raise the Alarm"))
    assert reasons
    assert any("create_token" in r for r in reasons)


def test_a_conditional_counter_is_refused(store) -> None:
    """Mana Leak needs a pay-or-not decision the engine has nowhere to put."""
    reasons = resolve.unsupported(store.by_name("Mana Leak"))
    assert reasons
    assert any("unless its controller pays" in r for r in reasons)


def test_a_card_with_an_unreadable_target_is_refused_whole(store) -> None:
    """All-or-nothing. Half-resolving a card is worse than not resolving it."""
    doom_blade = store.by_name("Doom Blade")  # "target nonblack creature"
    assert resolve.unsupported(doom_blade)
    assert resolve.plan_for(doom_blade) is None


def test_a_refused_card_has_no_plan(store) -> None:
    assert resolve.plan_for(store.by_name("Raise the Alarm")) is None


# --- casting through the action layer -----------------------------------


def test_a_removal_spell_offers_one_option_per_legal_target(store) -> None:
    bolt = store.by_name("Lightning Bolt")
    state = board(hand=[bolt], battlefield=[MOUNTAIN], opponent=[BEAR, GIANT])
    options = A.legal(state, 0, Step.PRECOMBAT_MAIN, stack_empty=True)
    casts = [o for o in options if isinstance(o, A.CastSpell)]
    # 2 creatures + 2 players for "any target"
    assert len(casts) == 4
    assert all(len(c.targets) == 1 for c in casts)


def test_a_targeted_spell_with_no_legal_target_cannot_be_cast(store) -> None:
    """CR 601.2c. Otherwise Murder gets cast into an empty board and fizzles."""
    murder = store.by_name("Murder")
    swamp = Card("s", "Swamp", parse_cost(None), "Basic Land — Swamp",
                 produces=frozenset("B"), taps_for_mana=True)
    state = board(hand=[murder], battlefield=[swamp] * 3)
    options = A.legal(state, 0, Step.PRECOMBAT_MAIN, stack_empty=True)
    assert [o for o in options if isinstance(o, A.CastSpell)] == []


def test_an_unresolvable_spell_is_still_castable_and_reported(store) -> None:
    """It does nothing, exactly as before — but says so rather than vanishing."""
    unresolvable = store.by_name("Raise the Alarm")
    plains = Card("p", "Plains", parse_cost(None), "Basic Land — Plains",
                  produces=frozenset("W"), taps_for_mana=True)
    state = board(hand=[unresolvable], battlefield=[plains] * 3)
    options = A.legal(state, 0, Step.PRECOMBAT_MAIN, stack_empty=True)
    casts = [o for o in options if isinstance(o, A.CastSpell)]
    assert len(casts) == 1
    assert casts[0].targets == ()


def test_targets_survive_the_move_to_the_stack(store) -> None:
    """A card changing zones becomes a new object (CR 400.7).

    Filing targets under the hand id leaves every spell resolving untargeted,
    which looks exactly like 'removal does nothing' rather than a bookkeeping bug.
    """
    bolt = store.by_name("Lightning Bolt")
    state = board(hand=[bolt], battlefield=[MOUNTAIN], opponent=[BEAR])
    game = Game(state, [CurveAgent(), PassingAgent()])

    spell = state.hand(0)[0]
    victim = state.battlefield(1)[0]
    game._apply(0, A.CastSpell(spell.id, (T.Target(object_id=victim.id),)))

    on_stack = state.zone(Zone.STACK)[0]
    assert on_stack.id != spell.id, "the object should be new on the stack"
    assert on_stack.id in game._targets, "targets were filed under a dead id"

    game._resolve_top()
    sba.check(state)
    assert state.battlefield(1) == [], "the bolt resolved without its target"


# --- counterspells ------------------------------------------------------


def test_a_counterspell_targets_the_stack_not_the_battlefield(store) -> None:
    state = board(opponent=[GIANT])
    spell = state.create(BEAR, owner=1, zone=Zone.STACK, controller=1)
    chosen = T.legal_targets(state, 0, T.TargetSpec(T.TargetKind.SPELL))
    assert [t.object_id for t in chosen] == [spell.id], (
        "a counterspell should see the stack, not the battlefield"
    )


def test_creature_and_noncreature_counters_discriminate(store) -> None:
    state = board()
    creature = state.create(BEAR, owner=1, zone=Zone.STACK, controller=1)
    burn = state.create(store.by_name("Lightning Bolt"), owner=1,
                        zone=Zone.STACK, controller=1)

    only_creature = T.legal_targets(state, 0, T.TargetSpec(T.TargetKind.CREATURE_SPELL))
    only_other = T.legal_targets(state, 0, T.TargetSpec(T.TargetKind.NONCREATURE_SPELL))
    assert [t.object_id for t in only_creature] == [creature.id]
    assert [t.object_id for t in only_other] == [burn.id]


def test_countering_puts_the_spell_in_the_graveyard(store) -> None:
    state = board()
    victim = state.create(BEAR, owner=1, zone=Zone.STACK, controller=1)
    cast_and_resolve(state, store.by_name("Counterspell"),
                     (T.Target(object_id=victim.id),))
    # `cast_and_resolve` only applies the verb; moving the counterspell itself
    # off the stack is the driver's job, so it is still there. What matters is
    # that its target left.
    assert victim.id not in state.objects
    assert state.battlefield(1) == [], "a countered permanent must not resolve"
    assert len(state.graveyard(1)) == 1


def test_a_countered_spell_is_no_longer_a_legal_target(store) -> None:
    """Counter-wars: the second counter fizzles if the first already ate it."""
    state = board()
    victim = state.create(BEAR, owner=1, zone=Zone.STACK, controller=1)
    target = T.Target(object_id=victim.id)
    spec = T.TargetSpec(T.TargetKind.SPELL)

    assert T.still_legal(state, 0, spec, target)
    state.move(victim, Zone.GRAVEYARD)
    assert not T.still_legal(state, 0, spec, target)


def test_a_counterspell_needs_something_on_the_stack(store) -> None:
    """CR 601.2c — with an empty stack there is nothing to point at."""
    island = Card("i", "Island", parse_cost(None), "Basic Land — Island",
                  produces=frozenset("U"), taps_for_mana=True)
    state = board(hand=[store.by_name("Counterspell")], battlefield=[island] * 3)
    options = A.legal(state, 0, Step.PRECOMBAT_MAIN, stack_empty=True)
    assert [o for o in options if isinstance(o, A.CastSpell)] == []


def test_the_pilot_never_counters_its_own_spell(store) -> None:
    state = board()
    mine = state.create(BEAR, owner=0, zone=Zone.STACK, controller=0)
    theirs = state.create(GIANT, owner=1, zone=Zone.STACK, controller=1)
    counter = state.create(store.by_name("Counterspell"), owner=0, zone=Zone.HAND)

    agent = CurveAgent()
    at_mine = A.CastSpell(counter.id, (T.Target(object_id=mine.id),))
    at_theirs = A.CastSpell(counter.id, (T.Target(object_id=theirs.id),))
    assert agent._spell_value(state, 0, at_theirs) > agent._spell_value(state, 0, at_mine)


def test_a_counterspell_stops_a_creature_in_a_real_game(store) -> None:
    """End to end through priority: cast, respond, resolve the counter first."""
    island = Card("i", "Island", parse_cost(None), "Basic Land — Island",
                  produces=frozenset("U"), taps_for_mana=True)
    counterspell = store.by_name("Counterspell")

    state = GameState.new([[], []], seed=0)
    state.active_player = 1
    for _ in range(4):
        state.create(island, owner=0, zone=Zone.BATTLEFIELD)
    state.create(counterspell, owner=0, zone=Zone.HAND)
    threat = state.create(BEAR, owner=1, zone=Zone.STACK, controller=1)

    game = Game(state, [CurveAgent(), CurveAgent()])
    game._priority(Step.PRECOMBAT_MAIN)

    assert threat.id not in state.objects or state.objects[threat.id].zone is Zone.GRAVEYARD
    assert not state.battlefield(1), "the countered creature reached the battlefield"


# --- sweepers -----------------------------------------------------------


def test_a_sweeper_destroys_both_boards(store) -> None:
    state = board(battlefield=[BEAR, GIANT], opponent=[BEAR, BEAR, GIANT])
    cast_and_resolve(state, store.by_name("Day of Judgment"))
    assert state.battlefield(0) == []
    assert state.battlefield(1) == []


def test_a_sweeper_does_not_skip_every_other_creature(store) -> None:
    """Iterating the battlefield while emptying it is the classic version of this bug."""
    state = board(battlefield=[BEAR] * 5, opponent=[GIANT] * 5)
    cast_and_resolve(state, store.by_name("Day of Judgment"))
    assert len(state.battlefield()) == 0, "some creatures were skipped"


def test_sweeping_damage_kills_only_what_it_is_big_enough_for(store) -> None:
    state = board(battlefield=[BEAR], opponent=[GIANT])   # Pyroclasm: 2 to each
    cast_and_resolve(state, store.by_name("Pyroclasm"))
    sba.check(state)
    assert state.battlefield(0) == [], "the 2/2 should have died"
    assert len(state.battlefield(1)) == 1, "the 5/5 should have survived"


def test_a_sweeper_on_an_empty_board_is_harmless(store) -> None:
    state = board()
    cast_and_resolve(state, store.by_name("Day of Judgment"))
    assert state.battlefield() == []


def test_a_sweeper_is_castable_with_no_creatures_out(store) -> None:
    """It takes no targets, so CR 601.2c does not restrict it."""
    plains = Card("p", "Plains", parse_cost(None), "Basic Land — Plains",
                  produces=frozenset("W"), taps_for_mana=True)
    state = board(hand=[store.by_name("Day of Judgment")], battlefield=[plains] * 4)
    options = A.legal(state, 0, Step.PRECOMBAT_MAIN, stack_empty=True)
    casts = [o for o in options if isinstance(o, A.CastSpell)]
    assert len(casts) == 1
    assert casts[0].targets == (), "a sweeper must not enumerate targets"


def test_a_mass_pump_is_refused(store) -> None:
    """Pump-as-counters is a bounded lie for one creature and a different card
    entirely when applied permanently to every creature on the board."""
    reasons = resolve.unsupported(store.by_name("Languish"))
    assert reasons
    assert any("duration model" in r for r in reasons)
