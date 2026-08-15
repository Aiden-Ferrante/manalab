"""Three and four player games.

The engine was always closer to N-player than its docs claimed — turn rotation,
priority, `game_over` and `Target` all counted players rather than assuming two.
Three places did assume it: the loss reason, who gets attacked, and who blocks.
These tests are about those three, and about the fact that a game with a player
eliminated keeps going.
"""

from __future__ import annotations

from manalab.cards.mana import parse_cost
from manalab.cards.model import Card
from manalab.engine import actions as A
from manalab.engine import sba
from manalab.engine.agents import PassingAgent
from manalab.engine.game import Game
from manalab.engine.state import GameState
from manalab.engine.zones import Zone

BEAR = Card("bear", "Grizzly Bears", parse_cost("{1}{G}"), "Creature — Bear",
            power="2", toughness="2")
FOREST = Card("forest", "Forest", parse_cost(None), "Basic Land — Forest",
              produces=frozenset("G"), taps_for_mana=True, oracle_text="")


def table(players: int = 4, life: int = 40) -> GameState:
    """A real-sized library: seven cards leave the top for an opening hand, and
    a short deck simply decks every player out before anything is observable."""
    return GameState.new([[FOREST] * 60 for _ in range(players)],
                         starting_life=life)


def test_a_table_of_four_starts_at_forty():
    state = table()
    assert len(state.players) == 4
    assert [p.life for p in state.players] == [40] * 4


def test_turns_rotate_round_the_whole_table():
    state = table()
    game = Game(state, [PassingAgent() for _ in range(4)], max_turns=8)
    game.setup()
    game.run()
    # (turn - 1) % 4, so eight turns is two full circuits.
    assert state.turn == 8


def test_an_attack_names_which_opponent():
    """With three or more players this is a real choice, and the one that
    decides most Commander games."""
    state = table(players=3)
    state.create(BEAR, owner=0, zone=Zone.BATTLEFIELD, quiet=True)
    for obj in state.battlefield(0):
        obj.summoning_sick = False

    options = A.legal_attacks(state, 0)
    attacking = [o for o in options if o.attackers]
    assert attacking, "no attack was offered"
    assert {o.defender for o in attacking} == {1, 2}, \
        "every living opponent should be attackable"


def test_only_the_attacked_player_blocks():
    state = table(players=3)
    attacker = state.create(BEAR, owner=0, zone=Zone.BATTLEFIELD, quiet=True)
    state.create(BEAR, owner=1, zone=Zone.BATTLEFIELD, quiet=True)
    state.create(BEAR, owner=2, zone=Zone.BATTLEFIELD, quiet=True)
    attacker.summoning_sick = False
    attacker.attacking = 2

    game = Game(state, [PassingAgent() for _ in range(3)])
    game._declare_blockers()

    # P1 was not attacked, so nothing of theirs is blocking.
    assert all(o.blocking is None for o in state.battlefield(1))


def test_damage_goes_to_the_player_who_was_attacked():
    state = table(players=3, life=20)
    attacker = state.create(BEAR, owner=0, zone=Zone.BATTLEFIELD, quiet=True)
    attacker.summoning_sick = False
    attacker.attacking = 2

    game = Game(state, [PassingAgent() for _ in range(3)])
    game._combat_damage()

    assert state.players[2].life == 18
    assert state.players[1].life == 20, "an unattacked player took damage"


def test_a_game_continues_after_one_player_is_eliminated():
    """`game_over` is "one player left standing", not "somebody lost"."""
    state = table(players=3)
    state.players[1].has_lost = True
    state.players[1].loss_reason = "life"

    assert not sba.game_over(state), "two players are still in the game"
    assert sba.winner(state) is None


def test_the_last_player_standing_wins():
    state = table(players=3)
    for index in (1, 2):
        state.players[index].has_lost = True

    assert sba.game_over(state)
    assert sba.winner(state) == 0


def test_an_eliminated_player_is_not_attackable():
    state = table(players=3)
    state.create(BEAR, owner=0, zone=Zone.BATTLEFIELD, quiet=True)
    for obj in state.battlefield(0):
        obj.summoning_sick = False
    state.players[1].has_lost = True

    options = A.legal_attacks(state, 0)
    assert {o.defender for o in options if o.attackers} == {2}


def test_a_four_player_game_runs_to_completion():
    """The integration check: nothing in the loop assumes two seats."""
    state = table()
    game = Game(state, [PassingAgent() for _ in range(4)], max_turns=12)
    game.setup()
    result = game.run()
    assert len(result.life) == 4
