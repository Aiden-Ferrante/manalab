"""Baselines. Several of these are embarrassingly hard to beat, which is the point.

An optimizer that cannot beat random sampling at equal budget is not an
optimizer, and on a noisy objective that failure is easy to miss without
something to measure against.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import manalab.search.compare as compare
import manalab.search.moves as moves
from manalab.search.oracle import Oracle

Vector = tuple[int, ...]


@dataclass
class RandomSearch:
    """Sample feasible decks, measure each once, keep the best.

    The honest floor. Also the cleanest demonstration of the winner's curse: with
    a large enough sample count the reported best is mostly noise, and the gap to
    its held-out score grows with how many decks were tried.
    """

    games_per_deck: int = 200
    max_stalls: int = 200
    """Consecutive free cache hits tolerated before concluding the pool is
    exhausted. Only bites on tiny pools, where it is the correct answer."""
    name: str = "random"

    def run(self, oracle: Oracle) -> Vector:
        bounds = oracle.pool.upper_bounds
        size = oracle.pool.deck_size
        best: Vector | None = None
        best_score = float("-inf")

        # A resampled deck is a free cache hit, so on a small pool the budget can
        # stop decreasing entirely once every deck has been seen. Without this
        # guard the loop spins forever on exactly the enumerable tier that the
        # benchmark uses for ground truth.
        stalled = 0
        while oracle.remaining >= self.games_per_deck and stalled < self.max_stalls:
            before = oracle.spent
            vector = moves.random_feasible(bounds, size, oracle.rng)
            estimate = oracle.evaluate(vector, self.games_per_deck, tag="candidate")
            stalled = 0 if oracle.spent > before else stalled + 1
            if estimate.score > best_score:
                best, best_score = estimate.vector, estimate.score

        if best is None:
            raise RuntimeError(
                f"budget {oracle.meter.total} too small for one deck at "
                f"{self.games_per_deck} games"
            )
        return best

    def config(self) -> Mapping[str, Any]:
        return {"games_per_deck": self.games_per_deck, "max_stalls": self.max_stalls}


@dataclass
class CoordinateSearch:
    """Gauss-Seidel line search along each swap direction in turn.

    On a simplex the only feasible "coordinate" is a direction `e_i - e_j`, so a
    coordinate sweep means: pick a pair of cards, move copies from one to the
    other while that keeps helping, then move to the next pair.

    Cheap, deterministic given a seed, and the baseline most likely to embarrass
    the clever methods — if the objective really is close to separable along
    single-card axes, this is near-optimal and nothing in Phase 4 will beat it by
    much. That would itself be the headline result.
    """

    games_per_eval: int = 400
    max_sweeps: int = 20
    alpha: float | None = None
    """If set, accept a move only when a *paired* test says it is a real
    improvement at this significance level, instead of whenever the measured
    score is higher.

    Accept-if-higher climbs on noise: across a 1-swap neighbourhood most
    differences are smaller than the measurement error, so roughly half of the
    apparent improvements are illusory and the search wanders. Requiring
    significance trades some progress for not moving backwards.
    """
    name: str = "coordinate"

    def run(self, oracle: Oracle) -> Vector:
        bounds = oracle.pool.upper_bounds
        current = oracle.problem.start or moves.random_feasible(
            bounds, oracle.pool.deck_size, oracle.rng
        )

        score = self._measure(oracle, current, "start")
        if score is None:
            return current

        n = len(bounds)
        directions = [(i, j) for i in range(n) for j in range(n) if i != j]

        for _ in range(self.max_sweeps):
            improved = False
            oracle.rng.shuffle(directions)

            for give, take in directions:
                # Move copies from `give` to `take` for as long as it helps.
                while moves.can_swap(current, bounds, give, take):
                    candidate = moves.swap(current, give, take)
                    candidate_score = self._measure(oracle, candidate, "line")
                    if candidate_score is None:
                        return current
                    if not self._accepts(oracle, candidate, current, candidate_score, score):
                        break
                    current, score, improved = candidate, candidate_score, True

            if not improved:
                break

        return current

    def _measure(self, oracle: Oracle, vector: Vector, tag: str) -> float | None:
        """Score a deck, or None when the budget cannot cover it."""
        if oracle.afford(self.games_per_eval, vector) < self.games_per_eval:
            return None
        return oracle.evaluate(vector, self.games_per_eval, tag=tag).score

    def _accepts(
        self,
        oracle: Oracle,
        candidate: Vector,
        current: Vector,
        candidate_score: float,
        score: float,
    ) -> bool:
        if self.alpha is None:
            return candidate_score > score
        # Both decks live on stream 0, so their samples are aligned game for
        # game and the difference gets the full CRN variance reduction.
        return (
            compare.paired(oracle.samples(candidate), oracle.samples(current)).verdict(
                self.alpha
            )
            == 1
        )

    def config(self) -> Mapping[str, Any]:
        return {
            "games_per_eval": self.games_per_eval,
            "max_sweeps": self.max_sweeps,
            "alpha": self.alpha,
        }


@dataclass
class FixedDeck:
    """Measure one deck and return it. The reference-decklist baseline.

    Spends its whole budget on precision rather than search, which makes it the
    most precisely measured entry in any comparison — useful, since it is the
    thing everything else has to beat.
    """

    vector: Vector
    name: str = "fixed"
    label: str = ""

    def run(self, oracle: Oracle) -> Vector:
        oracle.evaluate(self.vector, oracle.remaining, tag="reference")
        return self.vector

    def config(self) -> Mapping[str, Any]:
        return {"label": self.label, "vector": list(self.vector)}
