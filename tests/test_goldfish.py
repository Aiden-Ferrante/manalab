"""Simulator tests. Built on synthetic cards so they never need the card store."""

from __future__ import annotations

from manalab.cards.mana import parse_cost
from manalab.cards.model import Card, Decklist
from manalab.evaluate.consistency import ConsistencyEvaluator
from manalab.game import goldfish
from manalab.game.library import resolve


def land(name: str, colors: str, *, tapped: bool = False) -> Card:
    return Card(
        oracle_id=name,
        name=name,
        cost=parse_cost(None),
        type_line="Land",
        produces=frozenset(colors),
        taps_for_mana=True,
        enters_tapped=tapped,
        oracle_text="enters tapped" if tapped else "",
    )


def spell(name: str, cost: str, *, text: str = "", creature: bool = False) -> Card:
    return Card(
        oracle_id=name,
        name=name,
        cost=parse_cost(cost),
        type_line="Creature — Human" if creature else "Sorcery",
        oracle_text=text,
    )


MOUNTAIN = land("Mountain", "R")
BOLT = spell("Lightning Bolt", "{R}")
DRAGON = spell("Shivan Dragon", "{4}{R}{R}", creature=True)

CARDS = {c.name: c for c in (MOUNTAIN, BOLT, DRAGON)}
DECK = Decklist({"Mountain": 24, "Lightning Bolt": 20, "Shivan Dragon": 16}, "burn")


def test_same_seed_is_reproducible() -> None:
    library = resolve(DECK, CARDS)
    a = goldfish.play(library, seed=7)
    b = goldfish.play(library, seed=7)
    assert a == b


def test_different_seeds_diverge() -> None:
    library = resolve(DECK, CARDS)
    records = {goldfish.play(library, seed=s).opening_hand for s in range(20)}
    assert len(records) > 1


def test_all_lands_deck_curves_out_perfectly() -> None:
    """24 turns of land drops from a 60-land deck: mana should equal the turn number."""
    library = resolve(Decklist({"Mountain": 60}), CARDS)
    game = goldfish.play(library, seed=1, turns=6)
    assert game.mana_available == (1, 2, 3, 4, 5, 6)
    assert game.missed_land_drops == 0


def test_landless_deck_casts_nothing() -> None:
    library = resolve(Decklist({"Lightning Bolt": 60}), CARDS)
    game = goldfish.play(library, seed=1, turns=6)
    assert game.mana_available == (0,) * 6
    assert sum(game.spells_cast) == 0
    assert game.missed_land_drops == 6


def test_tapped_lands_delay_mana_by_one_turn() -> None:
    slow = land("Slow Land", "R", tapped=True)
    cards = {slow.name: slow}
    game = goldfish.play(resolve(Decklist({"Slow Land": 60}), cards), seed=1, turns=3)
    # Turn 1's land is tapped, so no mana until turn 2.
    assert game.mana_available == (0, 1, 2)


def test_on_the_draw_sees_an_extra_card() -> None:
    library = resolve(DECK, CARDS)
    play_ = goldfish.play(library, seed=3, turns=5, on_the_play=True)
    draw_ = goldfish.play(library, seed=3, turns=5, on_the_play=False)
    assert draw_.mana_available[-1] >= play_.mana_available[-1] - 1


def test_greedy_policy_casts_the_expensive_spell_when_it_can() -> None:
    library = resolve(Decklist({"Mountain": 40, "Shivan Dragon": 20}), CARDS)
    game = goldfish.play(library, seed=5, turns=10)
    assert "Shivan Dragon" in game.cast_turn
    assert game.cast_turn["Shivan Dragon"] >= 6  # a {4}{R}{R} needs six mana


def test_castability_is_independent_of_the_play_policy() -> None:
    """Two one-drops, one land: the policy casts one, but both were castable.

    This is the distinction that makes `--target` a mana-base measurement rather
    than a measurement of how the greedy policy breaks ties.
    """
    a = spell("Bolt A", "{R}")
    b = spell("Bolt B", "{R}")
    cards = {c.name: c for c in (MOUNTAIN, a, b)}
    deck = Decklist({"Mountain": 30, "Bolt A": 15, "Bolt B": 15})

    both_castable = both_cast = 0
    for seed in range(400):
        game = goldfish.play(resolve(deck, cards), seed=seed, turns=1)
        if game.castable_by("Bolt A", 1) and game.castable_by("Bolt B", 1):
            both_castable += 1
            if game.cast_by("Bolt A", 1) and game.cast_by("Bolt B", 1):
                both_cast += 1

    assert both_castable > 0, "expected hands holding both one-drops plus a land"
    assert both_cast == 0, "one land cannot cast two one-drops"


def test_unmodeled_cards_are_reported_not_ignored() -> None:
    cantrip = spell("Opt", "{U}", text="Scry 1. Draw a card.")
    found = goldfish.scan_unmodeled([BOLT, cantrip])
    assert "Lightning Bolt" not in found
    assert set(found["Opt"]) == {"card draw", "scry/surveil"}


def test_evaluator_surfaces_metrics_and_blind_spots() -> None:
    evaluator = ConsistencyEvaluator(cards=CARDS, targets=[("Shivan Dragon", 6)])
    result = evaluator.evaluate(DECK, n_games=200, seed=0)

    assert result.n_games == 200
    assert 0.0 <= result.metrics["p_on_curve_t3"] <= 1.0
    assert "castable_shivan_dragon_by_t6" in result.metrics
    assert (
        result.metrics["castable_shivan_dragon_by_t6"]
        >= result.metrics["cast_shivan_dragon_by_t6"]
    )
    assert result.stderr("p_on_curve_t3") > 0
    assert result.is_fully_modeled


def test_common_random_numbers_pair_the_two_decks() -> None:
    """Same seed => same shuffle stream => the paired difference is low-variance.

    A deck with two more lands should look at least as good on land drops, on
    essentially every seed, rather than only on average.
    """
    evaluator = ConsistencyEvaluator(cards=CARDS)
    lean = Decklist({"Mountain": 22, "Lightning Bolt": 38}, "22-land")
    rich = Decklist({"Mountain": 26, "Lightning Bolt": 34}, "26-land")

    a = evaluator.evaluate(lean, n_games=300, seed=99)
    b = evaluator.evaluate(rich, n_games=300, seed=99)

    assert b.metrics["p_on_curve_t4"] > a.metrics["p_on_curve_t4"]
