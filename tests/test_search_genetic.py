"""The genetic algorithm: legality of every operator, and budget discipline.

A GA is easy to write and easy to write *wrongly* in ways that still produce a
rising fitness curve. The tests that matter are not "does the score go up" —
that happens even when selection is broken — but "is every deck it produces a
legal deck", "does it stay inside its budget", and "does parallelism change the
answer".
"""

from __future__ import annotations

import random

import pytest

from manalab.cards.model import CandidatePool, Decklist
from manalab.evaluate.result import EvalResult
from manalab.search.genetic import GeneticSearch, crossover, mutate, random_genome, repair
from manalab.search.objective import LinearObjective
from manalab.search.problem import Problem
from manalab.search.runner import run_optimizer

POOL = CandidatePool(
    card_ids=tuple(f"c{i}" for i in range(20)) + ("Basic",),
    max_copies={"Basic": 60},
    deck_size=60,
)
BOUNDS = POOL.upper_bounds


class ToyEvaluator:
    """Scores a deck by a fixed per-card weight, plus reproducible noise.

    Deterministic in `(deck, seed)` and honours the game-i-at-seed-s+i contract,
    so the oracle's splicing works exactly as it does with the real evaluator.
    """

    name = "toy"

    def evaluate(self, deck: Decklist, *, n_games: int, seed: int) -> EvalResult:
        samples = []
        for i in range(n_games):
            rng = random.Random((seed + i) * 7919)
            signal = sum(int(c[1:]) * n for c, n in deck.counts.items() if c != "Basic")
            samples.append(signal / 1000.0 + rng.gauss(0, 0.1))
        return EvalResult(
            deck_name=deck.name,
            evaluator=self.name,
            n_games=n_games,
            seed=seed,
            metrics={"score": sum(samples) / len(samples)},
            samples={"score": tuple(samples)},
        )


OBJECTIVE = LinearObjective({"score": 1.0}, name="toy")


def problem(start=None) -> Problem:
    return Problem(pool=POOL, evaluator=ToyEvaluator(), objective=OBJECTIVE,
                   start=start, name="toy")


def legal(vector) -> bool:
    return sum(vector) == 60 and all(0 <= v <= b for v, b in zip(vector, BOUNDS))


# --- repair -------------------------------------------------------------


def test_repair_fixes_an_undersized_deck() -> None:
    assert legal(repair([0] * 21, BOUNDS, 60, random.Random(0)))


def test_repair_fixes_an_oversized_deck() -> None:
    assert legal(repair([4] * 20 + [60], BOUNDS, 60, random.Random(0)))


def test_repair_clamps_copies_over_the_limit() -> None:
    fixed = repair([99] * 20 + [0], BOUNDS, 60, random.Random(0))
    assert all(v <= b for v, b in zip(fixed, BOUNDS))
    assert legal(fixed)


def test_repair_leaves_a_legal_deck_alone() -> None:
    deck = tuple([3] * 20 + [0])
    assert sum(deck) == 60
    assert repair(deck, BOUNDS, 60, random.Random(0)) == deck


def test_repair_never_produces_negative_counts() -> None:
    fixed = repair([-5] * 20 + [80], BOUNDS, 60, random.Random(1))
    assert all(v >= 0 for v in fixed)


# --- the operators ------------------------------------------------------


def test_random_genomes_are_legal_and_varied() -> None:
    rng = random.Random(0)
    genomes = {random_genome(BOUNDS, 60, rng) for _ in range(30)}
    assert all(legal(g) for g in genomes)
    assert len(genomes) > 1, "initialisation produced no diversity"


def test_random_genomes_are_concentrated_not_spread_thin() -> None:
    """A deck is a few cards in multiples, not one copy each of eighty cards.

    Four-copy limits mean a 60-card deck needs at least fifteen distinct cards,
    so concentration cannot mean "very few names" — it means the names it does
    use are used in multiples, and the pool is mostly untouched.
    """
    big = CandidatePool(card_ids=tuple(f"c{i}" for i in range(130)), deck_size=60)
    rng = random.Random(0)

    for _ in range(10):
        genome = random_genome(big.upper_bounds, 60, rng, spread=12)
        used = [v for v in genome if v > 0]
        assert len(used) <= 25, "the deck is smeared across the pool"
        assert sum(used) == 60
        assert sum(1 for v in used if v >= 3) >= len(used) // 2, "mostly singletons"


def test_random_genomes_fill_to_size_even_when_spread_is_too_small() -> None:
    """Twelve cards at four copies hold 48; the set must grow to reach 60."""
    big = CandidatePool(card_ids=tuple(f"c{i}" for i in range(130)), deck_size=60)
    rng = random.Random(1)
    genome = random_genome(big.upper_bounds, 60, rng, spread=3)
    assert sum(genome) == 60
    assert all(v <= 4 for v in genome)


def test_crossover_takes_every_count_from_one_parent_or_the_other() -> None:
    a = tuple([4] * 15 + [0] * 6)
    b = tuple([0] * 15 + [4] * 5 + [40])
    child = crossover(a, b, random.Random(3))
    assert all(c in (x, y) for c, x, y in zip(child, a, b))


def test_crossover_of_identical_parents_is_that_parent() -> None:
    a = tuple([3] * 20 + [0])
    assert crossover(a, a, random.Random(0)) == a


def test_mutation_moves_something_but_not_everything() -> None:
    genome = tuple([3] * 20 + [0])
    mutated = mutate(genome, BOUNDS, random.Random(0), rate=1.0, step=1)
    assert mutated != genome
    assert all(abs(m - g) <= 1 for m, g in zip(mutated, genome))


def test_zero_mutation_rate_changes_nothing() -> None:
    genome = tuple([3] * 20 + [0])
    assert mutate(genome, BOUNDS, random.Random(0), rate=0.0) == genome


# --- the search itself --------------------------------------------------


def test_every_deck_the_ga_evaluates_is_legal() -> None:
    trace = run_optimizer(problem(), GeneticSearch(population=8, games_per_eval=5),
                          budget=400, seed=0)
    assert len(trace) > 0
    for evaluation in trace:
        assert legal(evaluation.estimate.vector)


def test_the_ga_respects_its_budget_exactly() -> None:
    trace = run_optimizer(problem(), GeneticSearch(population=8, games_per_eval=5),
                          budget=400, seed=0)
    assert trace.games_spent <= 400


def test_the_ga_improves_on_a_learnable_objective() -> None:
    """The toy objective rewards high-index cards, so a working GA finds them."""
    trace = run_optimizer(problem(), GeneticSearch(population=16, games_per_eval=5),
                          budget=4000, seed=0)
    curve = trace.incumbent_curve()
    assert curve[-1][1] > curve[0][1], "fitness never improved"


def test_the_ga_is_reproducible_at_a_seed() -> None:
    a = run_optimizer(problem(), GeneticSearch(population=8, games_per_eval=5),
                      budget=400, seed=4)
    b = run_optimizer(problem(), GeneticSearch(population=8, games_per_eval=5),
                      budget=400, seed=4)
    assert a.best.vector == b.best.vector
    assert [e.estimate.score for e in a] == [e.estimate.score for e in b]


def test_seeding_puts_the_start_deck_in_the_first_generation() -> None:
    start = tuple([0] * 20 + [60])
    ga = GeneticSearch(population=8, games_per_eval=5, seed_fraction=0.5)
    trace = run_optimizer(problem(start), ga, budget=200, seed=0)
    first_generation = [e.estimate.vector for e in trace][:8]
    assert start in first_generation


def test_a_cold_start_ignores_the_start_deck() -> None:
    start = tuple([0] * 20 + [60])
    ga = GeneticSearch(population=8, games_per_eval=5, seed_fraction=0.0)
    trace = run_optimizer(problem(start), ga, budget=200, seed=0)
    assert [e.estimate.vector for e in trace][:8].count(start) == 0


def test_elites_are_re_measured_on_a_fresh_stream_each_generation() -> None:
    """Otherwise a lucky score is cached forever and noise becomes permanent."""
    ga = GeneticSearch(population=6, games_per_eval=5, elite=2)
    trace = run_optimizer(problem(), ga, budget=600, seed=0)
    streams = {e.estimate.stream for e in trace}
    assert len(streams) > 1, "every generation reused one stream"


# --- parallelism --------------------------------------------------------


def test_workers_do_not_change_the_answer() -> None:
    """The whole justification for the fan-out: speed, and nothing else."""
    serial = run_optimizer(problem(), GeneticSearch(population=8, games_per_eval=5, workers=1),
                           budget=600, seed=2)
    parallel = run_optimizer(problem(), GeneticSearch(population=8, games_per_eval=5, workers=4),
                             budget=600, seed=2)
    assert serial.best.vector == parallel.best.vector
    assert [e.estimate.score for e in serial] == [e.estimate.score for e in parallel]
    assert serial.games_spent == parallel.games_spent
