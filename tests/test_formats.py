"""Constructed formats: legality, copy limits and deck construction.

`violations` takes a legality mapping rather than a store, so every test here is
a pure function call — no corpus, no DuckDB, no fixtures. That is the point of
the signature: checking a deck should not cost a query.
"""

from __future__ import annotations

import pytest

from manalab.cards import formats as F
from manalab.cards.model import Decklist

MODERN_POOL = {"Lightning Bolt": "legal", "Mountain": "legal", "Grizzly Bears": "legal"}
VINTAGE_POOL = {"Ancestral Recall": "restricted", "Black Lotus": "restricted",
                "Island": "legal", "Brainstorm": "restricted"}


def test_a_legal_constructed_deck_has_no_violations():
    deck = Decklist({"Lightning Bolt": 4, "Mountain": 56})
    assert F.MODERN.violations(deck, MODERN_POOL) == []
    assert F.MODERN.is_legal(deck, MODERN_POOL)


def test_the_copy_limit_is_enforced():
    deck = Decklist({"Lightning Bolt": 5, "Mountain": 55})
    (problem,) = F.MODERN.violations(deck, MODERN_POOL)
    assert "5 copies" in problem and "allows 4" in problem


def test_basic_lands_are_exempt_from_the_copy_limit():
    """CR 105.1a. A deck of 60 Mountains is legal; this is not a special case
    bolted on, it is why `unlimited` exists."""
    assert F.MODERN.violations(Decklist({"Mountain": 60}), MODERN_POOL) == []
    assert F.MODERN.copies_for("Mountain") == 60
    assert F.COMMANDER.copies_for("Mountain") == 100


def test_a_card_outside_the_format_is_named():
    deck = Decklist({"Black Lotus": 1, "Mountain": 59})
    (problem,) = F.MODERN.violations(deck, MODERN_POOL)
    assert problem == "Black Lotus is not legal in Modern"


def test_deck_size_is_checked():
    (problem,) = F.MODERN.violations(Decklist({"Mountain": 40}), MODERN_POOL)
    assert "40 cards" in problem and "wants 60" in problem


def test_restricted_means_one_copy_not_zero():
    """The distinction `legal_in` used to lose. A Vintage pool without its
    restricted cards is missing the format's defining cards."""
    one = Decklist({"Ancestral Recall": 1, "Island": 59})
    four = Decklist({"Ancestral Recall": 4, "Island": 56})
    assert F.VINTAGE.violations(one, VINTAGE_POOL) == []
    (problem,) = F.VINTAGE.violations(four, VINTAGE_POOL)
    assert "restricted" in problem and "allows 1" in problem


def test_restricted_is_capped_at_one_even_though_the_format_allows_four():
    assert F.VINTAGE.max_copies == 4
    assert F.VINTAGE.copies_for("Ancestral Recall", "restricted") == 1
    assert F.VINTAGE.copies_for("Brainstorm", "legal") == 4


def test_commander_is_singleton_at_a_hundred_cards():
    pool = {"Lightning Bolt": "legal", "Mountain": "legal"}
    assert F.COMMANDER.violations(Decklist({"Lightning Bolt": 1, "Mountain": 99}),
                                  pool) == []
    (problem,) = F.COMMANDER.violations(
        Decklist({"Lightning Bolt": 2, "Mountain": 98}), pool)
    assert "allows 1" in problem
    assert F.COMMANDER.singleton
    assert F.COMMANDER.starting_life == 40


def test_constructed_formats_are_not_singleton():
    assert not F.MODERN.singleton
    assert F.MODERN.starting_life == 20


def test_the_candidate_pool_carries_the_format_limits():
    """The bridge to search: a pool built from a format already knows that a
    basic is uncapped, a restricted card is one, and everything else is four."""
    pool = F.VINTAGE.candidate_pool(
        ["Ancestral Recall", "Island", "Brainstorm"], VINTAGE_POOL)
    assert pool.limit("Ancestral Recall") == 1
    assert pool.limit("Brainstorm") == 1        # also restricted in this fixture
    assert pool.limit("Island") == 60           # basic, capped by deck size
    assert pool.deck_size == 60


def test_a_commander_pool_is_singleton_all_the_way_down():
    pool = F.COMMANDER.candidate_pool(["Lightning Bolt", "Mountain"],
                                      {"Lightning Bolt": "legal", "Mountain": "legal"})
    assert pool.limit("Lightning Bolt") == 1
    assert pool.limit("Mountain") == 100
    assert pool.deck_size == 100


def test_lookup_accepts_a_name_or_a_legality_key():
    assert F.by_name("modern") is F.MODERN
    assert F.by_name("Modern") is F.MODERN
    assert F.by_name("  COMMANDER ") is F.COMMANDER


def test_an_unknown_format_raises_rather_than_falling_back():
    """A typo that silently became Modern would build a pool nobody asked for."""
    with pytest.raises(KeyError, match="unknown format"):
        F.by_name("moderrn")


def test_every_preset_names_a_real_scryfall_legality_field():
    from manalab.cards.store import PAPER_FORMATS

    for fmt in F.ALL:
        assert fmt.legality_key in PAPER_FORMATS, fmt.name
