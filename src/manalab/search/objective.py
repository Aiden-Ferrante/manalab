"""Objectives that expose per-game samples, not just a scalar.

`manalab.evaluate.Objective` is `EvalResult -> float`, which is all an optimizer
needs to rank two decks. It is *not* enough for anything statistical: racing,
paired tests and confidence intervals all need the per-game distribution of the
objective, and for a weighted sum of metrics that is not recoverable from the
metric standard errors alone (the terms covary).

So search uses `LinearObjective`, which knows how to push the weighting down to
the sample level. It satisfies the `Objective` protocol, so anything expecting a
plain callable still works.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from manalab.evaluate.result import EvalResult


@dataclass(frozen=True)
class LinearObjective:
    """A weighted sum of metrics, differentiable down to individual games.

    Negative weights are how you express costs: `{"p_on_curve_t4": 1.0,
    "mulligans": -0.1}` wants curve consistency but is willing to pay a little
    for it in mulligans.
    """

    terms: Mapping[str, float]
    name: str = ""

    def __post_init__(self) -> None:
        if not self.terms:
            raise ValueError("objective needs at least one term")
        object.__setattr__(self, "terms", dict(sorted(self.terms.items())))
        if not self.name:
            object.__setattr__(
                self, "name", "+".join(f"{w:g}*{k}" for k, w in self.terms.items())
            )

    def __call__(self, result: EvalResult) -> float:
        return sum(w * result.metrics.get(k, 0.0) for k, w in self.terms.items())

    def samples(self, result: EvalResult) -> tuple[float, ...]:
        """Per-game objective values.

        Raises if a term was not sampled per game — silently falling back to the
        scalar would produce a zero variance estimate, and a racing procedure
        handed zero variance will stop immediately and confidently.
        """
        columns: list[tuple[float, ...]] = []
        weights: list[float] = []

        for metric, weight in self.terms.items():
            xs = result.samples.get(metric)
            if xs is None:
                raise KeyError(
                    f"objective term {metric!r} has no per-game samples in "
                    f"{result.evaluator}; cannot compute objective variance"
                )
            columns.append(xs)
            weights.append(weight)

        lengths = {len(c) for c in columns}
        if len(lengths) != 1:
            raise ValueError(f"objective terms have mismatched sample counts: {lengths}")

        return tuple(
            sum(w * col[i] for w, col in zip(weights, columns))
            for i in range(lengths.pop())
        )


CONSISTENCY = LinearObjective({"p_on_curve_t4": 1.0}, name="consistency_t4")
THROUGHPUT = LinearObjective({"mana_spent": 1.0}, name="throughput")
"""Total mana converted into spells across the game — the objective with teeth.

Where consistency_t4 pays for mana *available* and nothing else (its optimum was
32+ lands and zero four-drops, found empirically), throughput pays only for mana
actually spent on spells, so it has an interior land optimum by construction:
too few lands and you cannot spend, too many and there is nothing to spend on.

Still synergy-blind, and honestly so: a spell's value here is its mana cost, so
an overcosted blank counts the same as a bomb. That is the *next* objective's
problem — this one exists so composition search stops being able to win by
cutting spells.
"""
"""Default working objective. Deliberately narrow and deliberately not "win rate".

Known to be gameable on its own — see the degenerate-deck problem in Phase 5 of
docs/M2_PROMPT.md. Fine for harness and allocator work, where what matters is
that the objective is noisy and cheap, not that it is the right objective.
"""
