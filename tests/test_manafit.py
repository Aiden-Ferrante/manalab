"""Bilevel mana fitting: the land base is derived, exactly, before evaluation."""

from __future__ import annotations

from manalab.cards.mana import parse_cost
from manalab.cards.model import Card, Decklist
from manalab.search.manafit import FittedEvaluator, fit_basics, pip_profile


def spell(name: str, cost: str) -> Card:
    return Card(oracle_id=name, name=name, cost=parse_cost(cost),
                type_line="Instant")


def lands_of(deck: Decklist) -> dict[str, int]:
    return {n: c for n, c in deck.counts.items()
            if n in {"Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes"}}


def test_mono_color_gets_one_basic():
    cards = {"Bolt": spell("Bolt", "{R}")}
    deck = fit_basics(Decklist({"Bolt": 4}), 24, cards)
    assert lands_of(deck) == {"Mountain": 24}
    assert sum(deck.counts.values()) == 28


def test_split_follows_pips_and_sums_exactly():
    """Largest-remainder: independent rounding drifts by ±1, and a 59-card deck
    is not a deck."""
    cards = {"R1": spell("R1", "{R}{R}"), "G1": spell("G1", "{G}")}
    deck = fit_basics(Decklist({"R1": 4, "G1": 4}), 23, cards)
    got = lands_of(deck)
    assert sum(got.values()) == 23
    assert got["Mountain"] > got["Forest"]        # 8 red pips vs 4 green
    assert got == {"Mountain": 15, "Forest": 8}   # 23 · 8/12 = 15.33 → 15


def test_a_splash_is_never_rounded_to_zero():
    """23 lands split 40:1 rounds the splash to zero — a deck that cannot cast
    two of its spells no matter how the shuffles fall."""
    cards = {"Main": spell("Main", "{R}{R}"), "Splash": spell("Splash", "{U}")}
    deck = fit_basics(Decklist({"Main": 20, "Splash": 1}), 23, cards)
    assert lands_of(deck)["Island"] >= 1


def test_hybrid_pips_split_fractionally():
    cards = {"Hy": spell("Hy", "{R/G}")}
    profile = pip_profile(Decklist({"Hy": 4}), cards)
    assert profile == {"R": 2.0, "G": 2.0}


def test_no_colored_pips_means_wastes_not_a_guess():
    cards = {"Karn": spell("Karn", "{4}")}
    deck = fit_basics(Decklist({"Karn": 4}), 20, cards)
    assert lands_of(deck) == {"Wastes": 20}


def test_copies_weigh_the_profile():
    cards = {"R1": spell("R1", "{R}"), "G1": spell("G1", "{G}")}
    profile = pip_profile(Decklist({"R1": 4, "G1": 1}), cards)
    assert profile == {"R": 4.0, "G": 1.0}


def test_zero_lands_is_just_the_spells():
    cards = {"Bolt": spell("Bolt", "{R}")}
    deck = fit_basics(Decklist({"Bolt": 4}), 0, cards)
    assert lands_of(deck) == {}


def test_the_wrapper_fits_before_the_inner_evaluator_sees_the_deck():
    seen: dict = {}

    class Probe:
        def evaluate(self, deck, *, n_games, seed):
            seen["deck"] = deck
            seen["seed"] = seed
            return None

    cards = {"Bolt": spell("Bolt", "{R}")}
    fitted = FittedEvaluator(inner=Probe(), cards=cards, lands=24)
    fitted.evaluate(Decklist({"Bolt": 36}), n_games=10, seed=7)
    assert seen["deck"].counts["Mountain"] == 24, "the inner sees a fitted deck"
    assert seen["seed"] == 7, "CRN seeds pass through untouched"
