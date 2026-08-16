"""Casting the commander, and the four-seat evaluator."""

from __future__ import annotations

from manalab.cards.mana import parse_cost
from manalab.cards.model import Card
from manalab.engine import actions as A
from manalab.engine import commander as C
from manalab.engine.agents import PassingAgent
from manalab.engine.game import Game
from manalab.engine.state import GameState
from manalab.engine.steps import Step
from manalab.engine.zones import Zone
from manalab.evaluate.commander import CommanderDeck, CommanderEvaluator

FOREST = Card("f", "Forest", parse_cost(None), "Basic Land — Forest",
              produces=frozenset("G"), taps_for_mana=True, oracle_text="")
GENERAL = Card("g", "Yeva, Test Herald", parse_cost("{1}{G}"),
               "Legendary Creature — Elf", power="2", toughness="2")
BEAR = Card("b", "Grizzly Bears", parse_cost("{1}{G}"), "Creature — Bear",
            power="2", toughness="2")


def test_a_commander_is_castable_from_the_command_zone():
    state = GameState.new([[FOREST] * 40, [FOREST] * 40])
    general = state.create(GENERAL, owner=0, zone=Zone.COMMAND, quiet=True)
    general.is_commander = True
    for _ in range(2):
        state.create(FOREST, owner=0, zone=Zone.BATTLEFIELD, quiet=True)

    options = A.legal(state, 0, Step.PRECOMBAT_MAIN, stack_empty=True)
    casts = [o for o in options if isinstance(o, A.CastSpell)
             and o.object_id == general.id]
    assert casts, "the commander was never offered as a cast"

    game = Game(state, [PassingAgent(), PassingAgent()])
    game._apply(0, casts[0])
    game._resolve_top()
    assert [o.card.name for o in state.battlefield(0) if o.is_creature] \
        == ["Yeva, Test Herald"]
    assert state.players[0].commander_casts == 1


def test_the_second_cast_costs_two_more():
    """The tax finally has a caller: killed once, the commander returns to the
    command zone and is only offered again when the extra {2} is payable."""
    state = GameState.new([[FOREST] * 40, [FOREST] * 40])
    general = state.create(GENERAL, owner=0, zone=Zone.COMMAND, quiet=True)
    general.is_commander = True
    state.players[0].commander_casts = 1        # one prior cast on record
    for _ in range(2):
        state.create(FOREST, owner=0, zone=Zone.BATTLEFIELD, quiet=True)

    offered = [o for o in A.legal(state, 0, Step.PRECOMBAT_MAIN, stack_empty=True)
               if isinstance(o, A.CastSpell)]
    assert not offered, "two lands cannot pay {1}{G} plus the {2} tax"

    for _ in range(2):
        state.create(FOREST, owner=0, zone=Zone.BATTLEFIELD, quiet=True)
    offered = [o for o in A.legal(state, 0, Step.PRECOMBAT_MAIN, stack_empty=True)
               if isinstance(o, A.CastSpell)]
    assert offered, "four lands pay it"


def _deck(name: str) -> CommanderDeck:
    return CommanderDeck(name, GENERAL, tuple([FOREST] * 24 + [BEAR] * 15))


def test_the_evaluator_runs_a_real_four_seat_table():
    ev = CommanderEvaluator([_deck("g1"), _deck("g2"), _deck("g3")])
    result = ev.evaluate(_deck("candidate"), n_games=4, seed=11)
    assert len(result.samples["win_rate"]) == 4
    assert all(w in (0.0, 1.0) for w in result.samples["win_rate"])
    assert result.metrics["game_length"] > 0


def test_the_evaluator_is_reproducible():
    ev = CommanderEvaluator([_deck("g1"), _deck("g2"), _deck("g3")])
    a = ev.evaluate(_deck("candidate"), n_games=3, seed=5)
    b = ev.evaluate(_deck("candidate"), n_games=3, seed=5)
    assert a.samples == b.samples


def test_game_i_equals_seed_s_plus_i():
    """The splicing contract every other evaluator honours."""
    ev = CommanderEvaluator([_deck("g1"), _deck("g2"), _deck("g3")])
    whole = ev.evaluate(_deck("candidate"), n_games=4, seed=100)
    for i in range(4):
        one = ev.evaluate(_deck("candidate"), n_games=1, seed=100 + i)
        assert one.samples["win_rate"][0] == whole.samples["win_rate"][i]


def test_the_decklist_adapter_speaks_the_search_protocol():
    """A Decklist in, an EvalResult out — the seam the GA and Oracle need."""
    from manalab.cards.model import Decklist
    from manalab.evaluate.commander import CommanderDecklistEvaluator

    cards = {c.name: c for c in (FOREST, GENERAL, BEAR)}
    ev = CommanderDecklistEvaluator(
        GENERAL.name, cards, [_deck("g1"), _deck("g2"), _deck("g3")])
    # The searcher owns the library; the adapter supplies the general — a
    # search that could drop its own commander would just be constructed.
    deck = Decklist({"Forest": 24, "Grizzly Bears": 15}, "list")
    result = ev.evaluate(deck, n_games=2, seed=3)
    assert len(result.samples["win_rate"]) == 2
