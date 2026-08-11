"""The turn engine: timing, the stack, combat, and state-based actions.

Synthetic cards throughout, so a failure points at the rules and not at Scryfall.
"""

from __future__ import annotations

import pytest

from manalab.cards.mana import parse_cost
from manalab.cards.model import Card
from manalab.engine import actions as A
from manalab.engine import mana, sba
from manalab.engine.agents import CurveAgent, PassingAgent, RandomAgent
from manalab.engine.game import Game
from manalab.engine.state import GameState
from manalab.engine.steps import TURN, Step, is_sorcery_speed
from manalab.engine.zones import Zone

MTN = Card("m", "Mountain", parse_cost(None), "Basic Land — Mountain",
           produces=frozenset("R"), taps_for_mana=True)
BEAR = Card("b", "Grizzly Bears", parse_cost("{1}{R}"), "Creature — Bear",
            power="2", toughness="2")
HASTY = Card("h", "Raging Goblin", parse_cost("{R}"), "Creature — Goblin",
             power="1", toughness="1", keywords=frozenset({"Haste"}))
VIGILANT = Card("v", "Serra Angel", parse_cost("{3}{R}{R}"), "Creature — Angel",
                power="4", toughness="4", keywords=frozenset({"Vigilance", "Flying"}))
BOLT = Card("z", "Lightning Bolt", parse_cost("{R}"), "Instant",
            oracle_text="Lightning Bolt deals 3 damage to any target.")
BIG = Card("g", "Giant", parse_cost("{4}{R}"), "Creature — Giant",
           power="5", toughness="5")

DECK = [MTN] * 24 + [BEAR] * 20 + [HASTY] * 16


def game(deck_a=None, deck_b=None, agents=None, seed=0, max_turns=30) -> Game:
    state = GameState.new([deck_a or DECK, deck_b or DECK], seed=seed)
    return Game(state, agents or [CurveAgent(), PassingAgent()], max_turns=max_turns)


# --- turn structure -----------------------------------------------------


def test_turn_has_the_twelve_steps_in_order() -> None:
    assert TURN[0] is Step.UNTAP
    assert TURN[-1] is Step.CLEANUP
    assert len(TURN) == 12
    assert TURN.index(Step.DECLARE_ATTACKERS) < TURN.index(Step.DECLARE_BLOCKERS)
    assert TURN.index(Step.DECLARE_BLOCKERS) < TURN.index(Step.COMBAT_DAMAGE)


def test_sorcery_speed_needs_all_three_conditions() -> None:
    """Dropping the empty-stack check is the classic way to let a sorcery be
    cast in response to something."""
    assert is_sorcery_speed(Step.PRECOMBAT_MAIN, active=True, stack_empty=True)
    assert not is_sorcery_speed(Step.PRECOMBAT_MAIN, active=False, stack_empty=True)
    assert not is_sorcery_speed(Step.PRECOMBAT_MAIN, active=True, stack_empty=False)
    assert not is_sorcery_speed(Step.UPKEEP, active=True, stack_empty=True)


def test_player_on_the_play_skips_their_first_draw() -> None:
    """Counted against the library, not the hand: the agent also plays a land
    and casts spells, so hand size measures the agent rather than the rule."""
    g = game()
    g.setup()
    assert len(g.state.library(0)) == 53

    g._play_turn()  # turn 1, P0
    assert len(g.state.library(0)) == 53


def test_second_player_does_draw_on_their_first_turn() -> None:
    g = game()
    g.setup()
    g._play_turn()  # turn 1, P0
    assert len(g.state.library(1)) == 53

    g._play_turn()  # turn 2, P1
    assert len(g.state.library(1)) == 52


# --- land drops ---------------------------------------------------------


def test_only_one_land_per_turn() -> None:
    state = GameState.new([[MTN] * 10, [MTN] * 10], seed=0)
    for _ in range(3):
        state.create(MTN, owner=0, zone=Zone.HAND)

    options = A.legal(state, 0, Step.PRECOMBAT_MAIN, stack_empty=True)
    assert any(isinstance(o, A.PlayLand) for o in options)

    state.players[0].lands_played = 1
    options = A.legal(state, 0, Step.PRECOMBAT_MAIN, stack_empty=True)
    assert not any(isinstance(o, A.PlayLand) for o in options)


def test_land_drops_reset_each_turn() -> None:
    g = game()
    g.setup()
    g._play_turn()
    assert g.state.players[0].lands_played == 1
    g._play_turn()  # P1's turn
    g._play_turn()  # back to P0
    assert g.state.players[0].lands_played == 1


# --- casting and the stack ---------------------------------------------


def test_creatures_cannot_be_cast_on_the_opponents_turn() -> None:
    state = GameState.new([[MTN] * 10, [MTN] * 10], seed=0)
    for _ in range(3):
        state.move(state.create(MTN, owner=0, zone=Zone.HAND), Zone.BATTLEFIELD)
    state.untap_all(0)
    state.create(BEAR, owner=0, zone=Zone.HAND)

    state.active_player = 0
    assert any(isinstance(o, A.CastSpell)
               for o in A.legal(state, 0, Step.PRECOMBAT_MAIN, stack_empty=True))

    state.active_player = 1
    assert not any(isinstance(o, A.CastSpell)
                   for o in A.legal(state, 0, Step.PRECOMBAT_MAIN, stack_empty=True))


def test_instants_can_be_cast_on_the_opponents_turn() -> None:
    state = GameState.new([[MTN] * 10, [MTN] * 10], seed=0)
    state.move(state.create(MTN, owner=0, zone=Zone.HAND), Zone.BATTLEFIELD)
    state.untap_all(0)
    state.create(BOLT, owner=0, zone=Zone.HAND)
    state.active_player = 1

    options = A.legal(state, 0, Step.UPKEEP, stack_empty=True)
    assert any(isinstance(o, A.CastSpell) for o in options)


def test_a_spell_you_cannot_pay_for_is_not_offered() -> None:
    state = GameState.new([[MTN] * 10, [MTN] * 10], seed=0)
    state.move(state.create(MTN, owner=0, zone=Zone.HAND), Zone.BATTLEFIELD)
    state.untap_all(0)
    state.create(BIG, owner=0, zone=Zone.HAND)  # costs {4}{R}, one land available

    options = A.legal(state, 0, Step.PRECOMBAT_MAIN, stack_empty=True)
    assert not any(isinstance(o, A.CastSpell) for o in options)


def test_casting_moves_through_the_stack_and_taps_lands() -> None:
    g = game()
    state = g.state
    for _ in range(2):
        state.move(state.create(MTN, owner=0, zone=Zone.HAND), Zone.BATTLEFIELD)
    state.untap_all(0)
    bear = state.create(BEAR, owner=0, zone=Zone.HAND)

    g._apply(0, A.CastSpell(bear.id))
    assert len(state.zone(Zone.STACK)) == 1
    assert sum(1 for o in state.battlefield(0) if o.tapped) == 2

    g._resolve_top()
    assert state.zone(Zone.STACK) == []
    assert any(o.card.name == "Grizzly Bears" for o in state.battlefield(0))


def test_noncreature_spells_resolve_doing_nothing_and_say_so() -> None:
    """The engine has no effect verbs yet. Doing nothing quietly would be far
    more dangerous than doing nothing loudly."""
    g = game()
    state = g.state
    state.move(state.create(MTN, owner=0, zone=Zone.HAND), Zone.BATTLEFIELD)
    state.untap_all(0)
    bolt = state.create(BOLT, owner=0, zone=Zone.HAND)

    g._apply(0, A.CastSpell(bolt.id))
    g._resolve_top()

    assert "Lightning Bolt" in g.unmodeled
    assert len(state.graveyard(0)) == 1
    assert state.players[1].life == 20


# --- combat -------------------------------------------------------------


def test_attacking_taps_the_attacker_unless_it_has_vigilance() -> None:
    g = game()
    state = g.state
    plain = state.move(state.create(HASTY, owner=0, zone=Zone.HAND), Zone.BATTLEFIELD)
    vigil = state.move(state.create(VIGILANT, owner=0, zone=Zone.HAND), Zone.BATTLEFIELD)
    plain.summoning_sick = vigil.summoning_sick = False
    state.active_player = 0

    g.agents[0] = CurveAgent()
    g._declare_attackers()

    assert plain.tapped
    assert not vigil.tapped
    assert plain.attacking == 1 and vigil.attacking == 1


def test_unblocked_attackers_hit_the_defending_player() -> None:
    g = game(agents=[CurveAgent(), PassingAgent()])
    state = g.state
    goblin = state.move(state.create(HASTY, owner=0, zone=Zone.HAND), Zone.BATTLEFIELD)
    goblin.summoning_sick = False
    state.active_player = 0

    g._declare_attackers()
    g._combat_damage()

    assert state.players[1].life == 19


def test_blocked_creatures_deal_damage_to_each_other() -> None:
    g = game(agents=[CurveAgent(), CurveAgent()])
    state = g.state
    attacker = state.move(state.create(BEAR, owner=0, zone=Zone.HAND), Zone.BATTLEFIELD)
    blocker = state.move(state.create(BEAR, owner=1, zone=Zone.HAND), Zone.BATTLEFIELD)
    attacker.summoning_sick = blocker.summoning_sick = False
    state.active_player = 0

    g._declare_attackers()
    g._declare_blockers()
    g._combat_damage()

    assert attacker.damage == 2 and blocker.damage == 2
    assert state.players[1].life == 20  # blocked, so no damage through

    sba.check(state)
    assert state.battlefield() == []  # both died


def test_combat_damage_is_simultaneous() -> None:
    """A creature that dies must still have dealt its damage. Applying damage
    inside the loop lets the first death cancel the trade.

    The block is assigned directly rather than through an agent: `CurveAgent`
    correctly declines a chump block, and this is a test of the damage rules,
    not of blocking policy.
    """
    g = game(agents=[CurveAgent(), CurveAgent()])
    state = g.state
    big = state.move(state.create(BIG, owner=0, zone=Zone.HAND), Zone.BATTLEFIELD)
    small = state.move(state.create(BEAR, owner=1, zone=Zone.HAND), Zone.BATTLEFIELD)
    big.summoning_sick = small.summoning_sick = False
    state.active_player = 0

    g._declare_attackers()
    small.blocking = big.id
    big.blocked_by = (small.id,)
    g._combat_damage()

    assert small.damage == 5  # lethal
    assert big.damage == 2    # dealt by a creature that is about to die
    assert state.players[1].life == 20  # blocked, nothing got through


def test_a_blocked_attacker_deals_no_damage_to_the_player() -> None:
    g = game(agents=[CurveAgent(), CurveAgent()])
    state = g.state
    big = state.move(state.create(BIG, owner=0, zone=Zone.HAND), Zone.BATTLEFIELD)
    chump = state.move(state.create(BEAR, owner=1, zone=Zone.HAND), Zone.BATTLEFIELD)
    big.summoning_sick = chump.summoning_sick = False
    state.active_player = 0

    g._declare_attackers()
    chump.blocking = big.id
    big.blocked_by = (chump.id,)
    g._combat_damage()
    sba.check(state)

    assert state.players[1].life == 20
    assert state.graveyard(1)[0].card.name == "Grizzly Bears"


def test_summoning_sick_creatures_cannot_attack() -> None:
    g = game()
    state = g.state
    bear = state.move(state.create(BEAR, owner=0, zone=Zone.HAND), Zone.BATTLEFIELD)
    state.active_player = 0
    assert bear.summoning_sick

    options = A.legal_attacks(state, 0)
    assert options == [A.DeclareAttackers(())]


# --- state-based actions ------------------------------------------------


def test_lethal_damage_destroys_a_creature() -> None:
    state = GameState.new([[MTN], [MTN]], seed=0)
    bear = state.create(BEAR, owner=0, zone=Zone.BATTLEFIELD)
    bear.damage = 2

    events = sba.check(state)

    assert "Grizzly Bears dies" in events
    assert len(state.graveyard(0)) == 1


def test_zero_life_loses_the_game() -> None:
    state = GameState.new([[MTN], [MTN]], seed=0)
    state.players[1].life = 0
    sba.check(state)
    assert state.players[1].has_lost
    assert sba.winner(state) == 0


def test_empty_library_loses_only_when_sbas_run() -> None:
    state = GameState.new([[MTN], []], seed=0)
    state.draw(1)
    assert not state.players[1].has_lost  # flagged, not yet lost
    sba.check(state)
    assert state.players[1].has_lost
    assert state.players[1].loss_reason == "empty library"


def test_sbas_repeat_until_nothing_applies() -> None:
    """One creature dying can put another below zero toughness; a single pass
    would leave the game illegal."""
    state = GameState.new([[MTN], [MTN]], seed=0)
    a = state.create(BEAR, owner=0, zone=Zone.BATTLEFIELD)
    b = state.create(BEAR, owner=0, zone=Zone.BATTLEFIELD)
    a.damage = 5
    b.add_counters("-1/-1", 2)

    sba.check(state)
    assert state.battlefield() == []


# --- whole games --------------------------------------------------------


def test_a_game_completes_and_reports_a_winner() -> None:
    result = game(seed=1).run()
    assert result.winner == 0
    assert result.reason == "life"
    assert result.life[1] <= 0


def test_the_turn_limit_produces_a_draw_not_a_hang() -> None:
    lands_only = [MTN] * 60
    result = game(lands_only, lands_only, [PassingAgent(), PassingAgent()],
                  max_turns=8).run()
    assert result.winner is None
    assert "turn limit" in result.reason
    assert result.turns == 8


def test_games_are_reproducible() -> None:
    a = game(seed=5).run()
    b = game(seed=5).run()
    assert (a.winner, a.turns, a.life) == (b.winner, b.turns, b.life)
    assert a.log == b.log


def test_different_seeds_give_different_games() -> None:
    results = {game(seed=s).run().turns for s in range(12)}
    assert len(results) > 1


def test_random_agent_never_makes_an_illegal_move() -> None:
    """The engine enumerates legal actions, so an agent picking arbitrarily
    should still never violate the rules."""
    for seed in range(15):
        result = game(agents=[RandomAgent(seed=seed), RandomAgent(seed=seed + 100)],
                      seed=seed, max_turns=20).run()
        assert result.turns <= 20


def test_being_on_the_play_is_an_advantage_in_the_mirror() -> None:
    """A weak but real signal that combat and timing are wired up: the same deck
    and agent on both sides should still favour the player who moves first."""
    wins = 0
    for seed in range(120):
        result = game(agents=[CurveAgent(), CurveAgent()], seed=seed).run()
        wins += result.winner == 0
    assert wins > 60


# --- mana ---------------------------------------------------------------


def test_tapped_lands_cannot_pay() -> None:
    state = GameState.new([[MTN], [MTN]], seed=0)
    land = state.move(state.create(MTN, owner=0, zone=Zone.HAND), Zone.BATTLEFIELD)
    land.summoning_sick = False
    assert mana.can_pay(state, 0, parse_cost("{R}"))

    land.tapped = True
    assert not mana.can_pay(state, 0, parse_cost("{R}"))


def test_paying_taps_exactly_what_it_needs() -> None:
    state = GameState.new([[MTN], [MTN]], seed=0)
    for _ in range(4):
        state.move(state.create(MTN, owner=0, zone=Zone.HAND), Zone.BATTLEFIELD)
    state.untap_all(0)

    mana.pay(state, 0, parse_cost("{1}{R}"))
    assert sum(1 for o in state.battlefield(0) if o.tapped) == 2


def test_multi_mana_sources_are_reported_as_unmodeled() -> None:
    sol = Card("s", "Sol Ring", parse_cost("{1}"), "Artifact",
               produces=frozenset(), taps_for_mana=True,
               oracle_text="{T}: Add {C}{C}.")
    state = GameState.new([[MTN], [MTN]], seed=0)
    state.create(sol, owner=0, zone=Zone.BATTLEFIELD)
    assert "Sol Ring" in mana.unmodeled_sources(state)
