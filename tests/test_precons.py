"""Precon import: the decklist shape, and the fidelity report that must travel
with any deck used as an opponent."""

from __future__ import annotations

import pytest

from manalab.cards import precons
from manalab.cards.mana import parse_cost
from manalab.cards.model import Card

DECK = {
    "name": "Test Precon",
    "commander": [{"name": "Yeva, Test Herald", "count": 1}],
    "mainBoard": [
        {"name": "Forest", "count": 40},
        {"name": "Grizzly Bears", "count": 4},
        {"name": "Unknowable Horror", "count": 1},
    ],
}


def test_as_decklist_merges_commander_and_mainboard():
    commander, counts = precons.as_decklist(DECK)
    assert commander == "Yeva, Test Herald"
    assert counts["Forest"] == 40
    assert counts["Yeva, Test Herald"] == 1
    assert sum(counts.values()) == 46


def test_a_deck_without_a_commander_is_an_error():
    with pytest.raises(ValueError):
        precons.as_decklist({"name": "x", "mainBoard": []})


def test_fidelity_report_counts_the_whole_deck():
    """`faithful` is the executed fraction OF THE DECK, not of known cards —
    an opponent playing at 0.4 fidelity is a bias every result inherits."""
    forest = Card("f", "Forest", parse_cost(None), "Basic Land — Forest",
                  produces=frozenset("G"), taps_for_mana=True, oracle_text="")
    bear = Card("b", "Grizzly Bears", parse_cost("{1}{G}"), "Creature — Bear",
                power="2", toughness="2")
    weird = Card("w", "Yeva, Test Herald", parse_cost("{3}{G}"),
                 "Legendary Creature — Elf",
                 power="4", toughness="4",
                 oracle_text="You may cast creature spells as though they had flash.")
    cards = {c.name: c for c in (forest, bear, weird)}

    _, counts = precons.as_decklist(DECK)
    from manalab.evaluate.pool import precon_fidelity

    report = precon_fidelity(counts, cards)

    assert report["cards"] == 46
    assert report["known"] == pytest.approx(45 / 46)      # Unknowable Horror absent
    assert report["faithful"] == pytest.approx(44 / 46)   # commander's text refused
    assert "Unknowable Horror" in report["refused"]
    assert "Yeva, Test Herald" in report["refused"]
