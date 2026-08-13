"""A genetic algorithm over decklists.

The honest baseline. It needs no training data, no surrogate model and no
assumptions about the shape of the objective: it evaluates the true thing
directly and lets selection do the rest. Whatever a cleverer method later
claims, this is the number it has to beat to have bought anything.

The genome is the deck: an integer vector of card counts over a `CandidatePool`,
each entry within its copy limit, summing to the deck size. Every operator here
can break those constraints, and `repair` puts them back — which is the whole
trick that makes crossover and mutation legal on a constrained integer simplex
without needing a penalty term in the objective.

Three details that matter more than the operators:

  * **Selection is paired.** Candidates within a generation are compared on the
    same games via the oracle's common random numbers. Fitness differences of a
    couple of points are invisible otherwise, and that is most of them.
  * **Elites are re-measured, not remembered.** Carrying a lucky score forward
    lets noise, once it favours a deck, protect that deck forever — the standard
    way a noisy GA converges confidently on nothing.
  * **Budget is in games, not generations.** The run stops when the oracle is
    exhausted, so a comparison against another optimizer is fair by construction.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from manalab.search.budget import BudgetExceeded
from manalab.search.oracle import Oracle

Genome = tuple[int, ...]


def repair(vector: Sequence[int], bounds: Sequence[int], size: int, rng: random.Random) -> Genome:
    """Nearest legal decklist: clamp to copy limits, then fix the total.

    Adding and removing at random rather than proportionally is deliberate. A
    proportional fix drags every count toward the mean and quietly erases the
    spikiness — four copies of one card, zero of another — that a decklist is
    mostly made of.
    """
    counts = [max(0, min(int(v), b)) for v, b in zip(vector, bounds)]
    total = sum(counts)

    if total < size:
        headroom = [i for i, (c, b) in enumerate(zip(counts, bounds)) if c < b]
        while total < size and headroom:
            i = rng.choice(headroom)
            counts[i] += 1
            total += 1
            if counts[i] >= bounds[i]:
                headroom.remove(i)
    elif total > size:
        occupied = [i for i, c in enumerate(counts) if c > 0]
        while total > size and occupied:
            i = rng.choice(occupied)
            counts[i] -= 1
            total -= 1
            if counts[i] == 0:
                occupied.remove(i)

    return tuple(counts)


def random_genome(bounds: Sequence[int], size: int, rng: random.Random, *, spread: int = 12) -> Genome:
    """A random legal deck built from a handful of cards rather than all of them.

    Sampling counts uniformly over a 132-card pool gives every deck the same
    shape — about half a copy of everything — and the population starts with no
    diversity in the only dimension that matters. Picking a few cards and
    filling up mimics how decks are actually built.

    `spread` is a *minimum* number of distinct cards, not a maximum. The set
    keeps growing until its copy limits can actually hold a full deck, because
    twelve cards at four copies each hold forty-eight and a sixty-card deck does
    not fit. Stopping at `spread` regardless leaves the shortfall to `repair`,
    which scatters it uniformly over the entire pool — undoing the concentration
    this function exists to create, and burying the basic lands in the process.
    """
    order = list(range(len(bounds)))
    rng.shuffle(order)

    chosen: list[int] = []
    capacity = 0
    for index in order:
        if len(chosen) >= spread and capacity >= size:
            break
        chosen.append(index)
        capacity += bounds[index]

    counts = [0] * len(bounds)
    total = 0
    available = [i for i in chosen if bounds[i] > 0]
    while total < size and available:
        i = rng.choice(available)
        counts[i] += 1
        total += 1
        if counts[i] >= bounds[i]:
            available.remove(i)

    return repair(counts, bounds, size, rng)


def crossover(a: Genome, b: Genome, rng: random.Random) -> Genome:
    """Per-card blend: take each count from one parent or the other.

    Uniform rather than single-point, because a pool has no meaningful card
    order — a contiguous slice of a list sorted by name is not a coherent piece
    of a deck, so single-point crossover would inherit nothing structural.
    """
    return tuple(x if rng.random() < 0.5 else y for x, y in zip(a, b))


def mutate(
    genome: Genome, bounds: Sequence[int], rng: random.Random, *, rate: float, step: int = 1
) -> Genome:
    """Nudge a few counts up or down."""
    counts = list(genome)
    for i in range(len(counts)):
        if rng.random() < rate:
            counts[i] += rng.randint(-step, step)
    return tuple(counts)


@dataclass
class GeneticSearch:
    """Tournament-selection GA with elitism, paired evaluation and repair."""

    population: int = 48
    games_per_eval: int = 40
    elite: int = 4
    tournament: int = 3
    mutation_rate: float = 0.05
    mutation_step: int = 2
    init_spread: int = 12
    seed_fraction: float = 0.0
    """Share of the initial population grown from `problem.start` by mutation.

    Zero means a cold start: every deck is random, and the search has to find
    even the broad shape of a decklist for itself. That is the purest version of
    the experiment and by far the most expensive — over a 132-card pool a random
    deck contains a basic land only by luck, so early generations are mostly
    decks that cannot cast anything, and the first thing the GA has to rediscover
    is that lands exist.

    A non-zero fraction seeds part of the population near a known-sane deck while
    leaving the rest random, which asks the much more useful question: can the
    search *improve* on a reasonable starting point? Set it deliberately and
    report it, because it changes what a result means.
    """

    workers: int = 1
    """Processes used to simulate a generation. Fitness is the parallel part."""

    name: str = "genetic"

    def config(self) -> Mapping[str, Any]:
        return {
            "population": self.population,
            "games_per_eval": self.games_per_eval,
            "elite": self.elite,
            "tournament": self.tournament,
            "mutation_rate": self.mutation_rate,
            "mutation_step": self.mutation_step,
            "init_spread": self.init_spread,
            "seed_fraction": self.seed_fraction,
        }

    def initial(self, oracle: Oracle) -> list[Genome]:
        """The starting population — cold, seeded, or a mix of both."""
        rng = oracle.rng
        bounds = oracle.problem.pool.upper_bounds
        size = oracle.problem.pool.deck_size
        start = oracle.problem.start

        n_seeded = 0 if start is None else int(self.population * self.seed_fraction)
        genomes: list[Genome] = []

        if start is not None and n_seeded:
            genomes.append(tuple(start))  # the start itself, unmutated
            for _ in range(n_seeded - 1):
                child = mutate(
                    tuple(start), bounds, rng, rate=self.mutation_rate * 3, step=self.mutation_step
                )
                genomes.append(repair(child, bounds, size, rng))

        while len(genomes) < self.population:
            genomes.append(random_genome(bounds, size, rng, spread=self.init_spread))
        return genomes

    def run(self, oracle: Oracle) -> Genome:
        rng = oracle.rng
        bounds = oracle.problem.pool.upper_bounds
        size = oracle.problem.pool.deck_size

        genomes = self.initial(oracle)

        best: Genome = genomes[0]
        best_score = float("-inf")
        generation = 0

        while True:
            try:
                scored = self._score(oracle, genomes, generation)
            except BudgetExceeded:
                break
            if not scored:
                break

            scored.sort(key=lambda pair: pair[1], reverse=True)
            if scored[0][1] > best_score:
                best, best_score = scored[0]

            generation += 1
            if oracle.exhausted or not oracle.meter.can_afford(self.games_per_eval):
                break

            genomes = self._next_generation(scored, bounds, size, rng)

        return best

    # --- pieces ---------------------------------------------------------

    def _score(
        self, oracle: Oracle, genomes: Sequence[Genome], generation: int
    ) -> list[tuple[Genome, float]]:
        """Measure a whole generation on one shared random stream.

        The stream is the generation index, which does two things at once.
        Within a generation every deck meets identical games, so ranking them is
        a paired comparison and small real differences survive the noise. Across
        generations the stream changes, so an elite is genuinely re-measured
        rather than served its old score from the oracle's cache — otherwise a
        deck that got lucky once is protected by that luck for the rest of the
        run, and the population converges on a measurement error.
        """
        estimates = oracle.evaluate_many(
            genomes,
            self.games_per_eval,
            stream=generation,
            tag=f"gen{generation}",
            workers=self.workers,
        )
        return [(tuple(e.vector), e.score) for e in estimates]

    def _next_generation(
        self,
        scored: Sequence[tuple[Genome, float]],
        bounds: Sequence[int],
        size: int,
        rng: random.Random,
    ) -> list[Genome]:
        children: list[Genome] = [g for g, _ in scored[: self.elite]]

        while len(children) < self.population:
            parent_a = self._tournament(scored, rng)
            parent_b = self._tournament(scored, rng)
            child = crossover(parent_a, parent_b, rng)
            child = mutate(child, bounds, rng, rate=self.mutation_rate, step=self.mutation_step)
            children.append(repair(child, bounds, size, rng))

        return children[: self.population]

    def _tournament(self, scored: Sequence[tuple[Genome, float]], rng: random.Random) -> Genome:
        picked = rng.sample(range(len(scored)), min(self.tournament, len(scored)))
        best = max(picked, key=lambda i: scored[i][1])
        return scored[best][0]
