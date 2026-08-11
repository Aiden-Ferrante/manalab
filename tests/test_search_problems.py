"""Phase 1: the closed forms, the feasible-set enumeration, and the tiers.

The closed forms are ground truth for everything downstream, so they are checked
against hand-computable cases rather than against the simulator — otherwise a
shared misunderstanding would validate itself.
"""

from __future__ import annotations

from math import comb, isclose

import pytest

from manalab.cards.model import CandidatePool
from manalab.search.oracle import MAX_STREAMS, crn_base_for_run
from manalab.search.problems import (
    analytic_tier,
    count_feasible,
    enumerable_tier,
    enumerate_feasible,
    p_at_least,
    p_castable_one_drop,
)


# --- closed forms -------------------------------------------------------


def test_p_at_least_edge_cases() -> None:
    assert p_at_least(20, 40, 7, 0) == 1.0
    assert p_at_least(0, 40, 7, 1) == 0.0
    assert p_at_least(40, 40, 7, 7) == 1.0


def test_p_at_least_matches_the_complement_by_hand() -> None:
    """P(>=1 land in 7 from a 40-card deck with 20 lands) = 1 - C(20,7)/C(40,7)."""
    expected = 1 - comb(20, 7) / comb(40, 7)
    assert isclose(p_at_least(20, 40, 7, 1), expected, rel_tol=1e-12)


def test_castable_reduces_to_inclusion_exclusion() -> None:
    """With no filler, P(land and spell) = 1 - P(no land) - P(no spell)."""
    lands, spells, size = 20, 20, 40
    expected = 1 - comb(20, 7) / comb(40, 7) - comb(20, 7) / comb(40, 7)
    assert isclose(p_castable_one_drop(lands, spells, size), expected, rel_tol=1e-12)


def test_castable_is_symmetric_in_lands_and_spells() -> None:
    assert isclose(
        p_castable_one_drop(16, 12, 40), p_castable_one_drop(12, 16, 40), rel_tol=1e-12
    )


def test_castable_is_zero_without_one_of_the_pieces() -> None:
    assert p_castable_one_drop(0, 20, 40) == 0.0
    assert p_castable_one_drop(20, 0, 40) == 0.0


def test_castable_rejects_impossible_decks() -> None:
    with pytest.raises(ValueError):
        p_castable_one_drop(30, 30, 40)


# --- the analytic tier's optimum ---------------------------------------


def test_analytic_optimum_is_interior_and_beats_its_neighbours() -> None:
    """A monotone objective would make the tier worthless as a benchmark —
    every optimizer would 'win' by pushing one coordinate to its bound."""
    tier = analytic_tier(40)
    lands, spells, filler = tier.optimum

    assert filler == 0
    assert 0 < lands < 40 and 0 < spells < 40

    for delta in (-1, 1):
        neighbour = p_castable_one_drop(lands + delta, spells - delta, 40)
        assert neighbour < tier.optimum_score


def test_analytic_optimum_is_the_even_split() -> None:
    tier = analytic_tier(40)
    assert tier.optimum == (20, 20, 0)


# --- enumeration --------------------------------------------------------


def test_enumeration_yields_exactly_the_feasible_decks() -> None:
    pool = CandidatePool(("a", "b", "c"), max_copies={"a": 4, "b": 4, "c": 4}, deck_size=6)
    decks = list(enumerate_feasible(pool))

    assert len(decks) == len(set(decks))
    for deck in decks:
        assert sum(deck) == 6
        assert all(0 <= v <= 4 for v in deck)

    # Every legal combination is present, so brute force really is exhaustive.
    brute = [
        (a, b, 6 - a - b)
        for a in range(5)
        for b in range(5)
        if 0 <= 6 - a - b <= 4
    ]
    assert sorted(decks) == sorted(brute)


def test_enumeration_respects_a_binding_upper_bound() -> None:
    pool = CandidatePool(("a", "b"), max_copies={"a": 2, "b": 10}, deck_size=6)
    assert sorted(enumerate_feasible(pool)) == [(0, 6), (1, 5), (2, 4)]


def test_enumerable_tier_is_actually_enumerable() -> None:
    tier = enumerable_tier(24)
    n = count_feasible(tier.problem.pool)
    assert 0 < n < 2000, f"{n} decks is too many to brute-force as ground truth"


# --- stream blocks ------------------------------------------------------


def test_each_run_seed_gets_a_disjoint_stream_block() -> None:
    """Without this, replicating across seeds replays identical games and the
    benchmark reports a variance far below the truth."""
    a_lo = crn_base_for_run(0)
    b_lo = crn_base_for_run(1)
    a_hi = a_lo + (MAX_STREAMS - 1) * (1 << 32) + (1 << 32) - 1
    assert a_hi < b_lo
