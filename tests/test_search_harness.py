"""Phase 0 gate: budget accounting, reproducibility, and the CRN coupling.

Everything downstream in M2 rests on these. If traces are not byte-identical at
a fixed seed, every optimizer comparison is measuring noise in the harness.
"""

from __future__ import annotations

import pytest

from manalab.cards.mana import parse_cost
from manalab.cards.model import CandidatePool, Card, Decklist
from manalab.evaluate.consistency import ConsistencyEvaluator
from manalab.search import moves
from manalab.search.baselines import FixedDeck, RandomSearch
from manalab.search.budget import BudgetExceeded, BudgetMeter
from manalab.search.objective import LinearObjective
from manalab.search.oracle import Oracle
from manalab.search.problem import Problem
from manalab.search.runner import run_optimizer

# --- a small synthetic problem, so tests never need the card store ------


def land(name: str, color: str) -> Card:
    return Card(name, name, parse_cost(None), "Land",
                produces=frozenset(color), taps_for_mana=True)


def spell(name: str, cost: str) -> Card:
    return Card(name, name, parse_cost(cost), "Sorcery")


CARDS = {
    c.name: c
    for c in (
        land("Mountain", "R"),
        land("Plains", "W"),
        spell("One", "{R}"),
        spell("Three", "{2}{R}"),
        spell("Five", "{4}{W}"),
    )
}

POOL = CandidatePool(
    card_ids=("Mountain", "Plains", "One", "Three", "Five"),
    max_copies={"Mountain": 30, "Plains": 30, "One": 8, "Three": 8, "Five": 8},
    deck_size=40,
)

OBJECTIVE = LinearObjective({"p_on_curve_t3": 1.0}, name="curve_t3")


def make_problem(start=None) -> Problem:
    return Problem(
        pool=POOL,
        evaluator=ConsistencyEvaluator(cards=CARDS, turns=5, curve_turns=(2, 3, 4)),
        objective=OBJECTIVE,
        start=start,
        name="tiny",
    )


FEASIBLE = (16, 8, 8, 8, 0)


# --- budget -------------------------------------------------------------


def test_budget_meter_accounting() -> None:
    meter = BudgetMeter(100)
    meter.spend(40)
    assert (meter.spent, meter.remaining) == (40, 60)
    assert meter.can_afford(60) and not meter.can_afford(61)
    assert meter.clamp(500) == 60


def test_budget_overrun_raises_rather_than_warns() -> None:
    meter = BudgetMeter(10)
    with pytest.raises(BudgetExceeded):
        meter.spend(11)


def test_oracle_refuses_to_overspend() -> None:
    oracle = Oracle(make_problem(), budget=100, seed=0)
    oracle.evaluate(FEASIBLE, 100)
    assert oracle.exhausted
    with pytest.raises(BudgetExceeded):
        oracle.evaluate((15, 9, 8, 8, 0), 50)


def test_oracle_rejects_infeasible_decks() -> None:
    oracle = Oracle(make_problem(), budget=100, seed=0)
    with pytest.raises(ValueError):
        oracle.evaluate((1, 1, 1, 1, 1), 10)


# --- incremental sampling ----------------------------------------------


def test_repeat_measurement_is_free() -> None:
    oracle = Oracle(make_problem(), budget=1000, seed=0)
    oracle.evaluate(FEASIBLE, 200)
    oracle.evaluate(FEASIBLE, 200)
    assert oracle.spent == 200


def test_more_precision_buys_only_the_difference() -> None:
    """Racing works by topping up survivors; paying full price each time would
    make successive halving cost more than uniform allocation."""
    oracle = Oracle(make_problem(), budget=1000, seed=0)
    oracle.evaluate(FEASIBLE, 50)
    oracle.evaluate(FEASIBLE, 200)
    assert oracle.spent == 200


def test_incremental_sampling_matches_a_single_shot_run() -> None:
    """50-then-200 must equal a straight 200, or top-ups silently change the
    estimator and racing results stop being comparable to uniform ones."""
    stepped = Oracle(make_problem(), budget=1000, seed=0)
    stepped.evaluate(FEASIBLE, 50)
    a = stepped.evaluate(FEASIBLE, 200)

    direct = Oracle(make_problem(), budget=1000, seed=0)
    b = direct.evaluate(FEASIBLE, 200)

    assert a.score == pytest.approx(b.score)
    assert a.stderr == pytest.approx(b.stderr)


def test_measured_and_afford_do_not_spend() -> None:
    oracle = Oracle(make_problem(), budget=100, seed=0)
    assert oracle.measured(FEASIBLE) == 0
    assert oracle.afford(500, FEASIBLE) == 100
    assert oracle.spent == 0


# --- common random numbers ---------------------------------------------


def test_decks_share_a_stream_by_default() -> None:
    oracle = Oracle(make_problem(), budget=1000, seed=0)
    a = oracle.evaluate(FEASIBLE, 100)
    b = oracle.evaluate((17, 7, 8, 8, 0), 100)
    assert a.stream == b.stream == 0


def test_adjacent_streams_do_not_share_games() -> None:
    """Streams are indices mapped to disjoint seed blocks.

    Using the index directly as a seed offset makes stream 1 and stream 2 share
    every game but one, which turns an "independent" comparison into a paired
    one and understates its variance enormously.
    """
    oracle = Oracle(make_problem(), budget=10_000, seed=0)
    a = oracle.evaluate(FEASIBLE, 400, stream=1)
    b = oracle.evaluate(FEASIBLE, 400, stream=2)
    assert a.stream != b.stream
    assert a.score != b.score


def test_a_stream_cannot_run_into_the_next_one() -> None:
    from manalab.search.oracle import STREAM_STRIDE

    oracle = Oracle(make_problem(), budget=10, seed=0)
    with pytest.raises(ValueError, match="collide"):
        oracle.evaluate(FEASIBLE, STREAM_STRIDE + 1)


def test_crn_pairing_beats_independent_streams() -> None:
    """The claim the whole variance-reduction phase rests on.

    Two decks differing by one card, measured on a shared stream, should agree
    far more closely than the same decks measured on unrelated streams.
    """
    import statistics

    a_vec, b_vec = (16, 8, 8, 8, 0), (17, 7, 8, 8, 0)
    n = 400

    paired_gap = []
    independent_gap = []
    for trial in range(15):
        oracle = Oracle(make_problem(), budget=10_000, seed=trial)
        pa = oracle.evaluate(a_vec, n, stream=trial)
        pb = oracle.evaluate(b_vec, n, stream=trial)
        paired_gap.append(pa.score - pb.score)

        ia = oracle.evaluate(a_vec, n, stream=100 + trial)
        ib = oracle.evaluate(b_vec, n, stream=200 + trial)
        independent_gap.append(ia.score - ib.score)

    assert statistics.pstdev(paired_gap) < statistics.pstdev(independent_gap)


# --- reproducibility: the Phase 0 gate ---------------------------------


def test_identical_seeds_produce_identical_traces() -> None:
    a = run_optimizer(make_problem(), RandomSearch(games_per_deck=100),
                      budget=2000, seed=7)
    b = run_optimizer(make_problem(), RandomSearch(games_per_deck=100),
                      budget=2000, seed=7)
    assert a.digest() == b.digest()
    assert a.to_json() == b.to_json()


def test_different_seeds_produce_different_traces() -> None:
    a = run_optimizer(make_problem(), RandomSearch(games_per_deck=100),
                      budget=2000, seed=7)
    b = run_optimizer(make_problem(), RandomSearch(games_per_deck=100),
                      budget=2000, seed=8)
    assert a.digest() != b.digest()


def test_run_reports_exact_budget_use_and_a_feasible_deck() -> None:
    problem = make_problem()
    trace = run_optimizer(problem, RandomSearch(games_per_deck=100),
                          budget=2000, seed=1)
    assert trace.games_spent == 2000
    assert problem.is_feasible(tuple(trace.config["final_vector"]))
    # At least 20 paid evaluations; a resampled duplicate deck is a free cache
    # hit and adds a trace row without spending games.
    assert len(trace) >= 20
    assert sum(1 for e in trace if e.estimate.games) == len(trace)


def test_unmodeled_cards_propagate_into_the_trace() -> None:
    cards = dict(CARDS)
    cards["Cantrip"] = Card("Cantrip", "Cantrip", parse_cost("{R}"), "Sorcery",
                            oracle_text="Draw a card.")
    pool = CandidatePool(("Mountain", "Cantrip"),
                         max_copies={"Mountain": 40, "Cantrip": 40}, deck_size=40)
    problem = Problem(
        pool=pool,
        evaluator=ConsistencyEvaluator(cards=cards, turns=4, curve_turns=(2, 3)),
        objective=OBJECTIVE,
        name="cantrip",
    )
    trace = run_optimizer(problem, FixedDeck((20, 20)), budget=200, seed=0)
    assert trace.config["unmodeled_cards"] == ["Cantrip"]


# --- the feasible set ---------------------------------------------------


def test_random_feasible_respects_bounds_and_size() -> None:
    import random

    rng = random.Random(0)
    for _ in range(50):
        v = moves.random_feasible(POOL.upper_bounds, POOL.deck_size, rng)
        assert sum(v) == POOL.deck_size
        assert all(0 <= x <= u for x, u in zip(v, POOL.upper_bounds))


def test_swap_neighbors_are_all_feasible() -> None:
    problem = make_problem()
    for _, _, neighbor in moves.swap_neighbors(FEASIBLE, POOL.upper_bounds):
        assert problem.is_feasible(neighbor)
    assert moves.distance(FEASIBLE, (17, 7, 8, 8, 0)) == 1


def test_repair_projects_onto_the_feasible_set() -> None:
    import random

    rng = random.Random(0)
    problem = make_problem()
    for vector in [(0, 0, 0, 0, 0), (99, 99, 99, 99, 99), (3, -4, 40, 1, 2)]:
        fixed = moves.repair(vector, POOL.upper_bounds, POOL.deck_size, rng)
        assert problem.is_feasible(fixed)
