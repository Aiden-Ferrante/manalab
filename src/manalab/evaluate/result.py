"""Result and protocol types for the evaluation seam.

An `Evaluator` turns a decklist into numbers. It is the *only* thing the search
layer is allowed to know about Magic. Today the one implementation wraps a
goldfish simulator; tomorrow one may wrap Forge in a subprocess. Search must not
be able to tell the difference except by reading `EvalResult.evaluator`.

The rule that keeps this honest: nothing in `manalab.search` may import
`manalab.game`. `tests/test_architecture.py` enforces it.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Callable, Mapping, Protocol, Sequence, runtime_checkable

from manalab.cards.model import Decklist

__all__ = ["EvalResult", "Evaluator", "Objective", "metric"]


@dataclass(frozen=True)
class EvalResult:
    """What an evaluator returns. Deliberately not "a win rate".

    `metrics` are scalar summaries. `samples` keeps the per-game values so the
    search layer can compute confidence intervals and decide whether two decks
    are actually distinguishable — the difference between a search that works
    and one that chases noise.
    """

    deck_name: str
    evaluator: str
    n_games: int
    seed: int
    metrics: Mapping[str, float] = field(default_factory=dict)
    samples: Mapping[str, tuple[float, ...]] = field(default_factory=dict)
    unmodeled: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    """Cards whose behaviour the evaluator could not represent. Never empty-by-default:
    an evaluator that cannot detect its own blind spots should say so explicitly."""

    def stderr(self, name: str) -> float:
        """Standard error of a metric, or 0.0 if it wasn't sampled per-game."""
        xs = self.samples.get(name)
        if not xs or len(xs) < 2:
            return 0.0
        return statistics.stdev(xs) / (len(xs) ** 0.5)

    def ci95(self, name: str) -> tuple[float, float]:
        mu, se = self.metrics.get(name, 0.0), self.stderr(name)
        return (mu - 1.96 * se, mu + 1.96 * se)

    @property
    def is_fully_modeled(self) -> bool:
        return not self.unmodeled


@runtime_checkable
class Evaluator(Protocol):
    """The swappable fidelity layer.

    Implementations must be pure in `(deck, seed)`: the same seed must produce
    the same result. Common random numbers depend on it, and CRN is what makes
    deckbuilding search affordable.
    """

    name: str

    def evaluate(self, deck: Decklist, *, n_games: int, seed: int) -> EvalResult: ...


Objective = Callable[[EvalResult], float]
"""Maps a result to a single number that search maximises.

Kept separate from the evaluator on purpose. Changing what you're optimising for
should never require re-running simulations or touching the game model.
"""


def metric(name: str, *, weight: float = 1.0) -> Objective:
    """The simplest objective: maximise one metric."""

    def objective(result: EvalResult) -> float:
        return weight * result.metrics.get(name, 0.0)

    return objective


def weighted(**terms: float) -> Objective:
    """Linear combination of metrics, e.g. `weighted(p_on_curve_t4=1.0, mulligan_rate=-0.5)`."""

    def objective(result: EvalResult) -> float:
        return sum(w * result.metrics.get(k, 0.0) for k, w in terms.items())

    return objective
