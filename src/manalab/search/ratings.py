"""Card ratings by ridge regression over randomised decks.

The estimator half of the bulk method: given rows of (cards played, table, games,
wins) from `evaluate.bulk`, recover each card's marginal contribution to winning.
Because `search.sampler` assigns cards to decks by coin flip, the contrast is
randomised and the coefficients estimate a causal effect rather than a builder's
preferences.

Ridge, not ordinary least squares, because cards outnumber decks early in a
campaign and the design is collinear even later. The penalty buys a well-posed
problem at a stated price: **coefficients are shrunk toward zero on purpose**,
so magnitudes read low and only the ordering is worth much until the data is
deep. `cross_validated_alpha` picks the penalty from held-out error instead of
taste.

Table indicators ride along unpenalised. A deck that happened to face the
harder field should not have its cards blamed for it, and the five-table
campaign measured exactly how large that effect is — larger than the deck
differences it was trying to resolve.

Three limits, none of them fixable by more games:

  * **Co-occurring cards cannot be separated.** Two cards that always appear
    together form one column; ridge splits the credit between them evenly,
    which is a statement about the design matrix, not about the cards. Vary
    them independently or read them as a pair.
  * **Combos are invisible to a linear model.** A two-card win condition
    contributes nothing on its own, so each half rates near zero. Interaction
    terms or the port features from `search.ports` are the fix, per suspected
    pair, declared in advance.
  * **Everything is conditional on the pilot.** A card that rewards skilled
    play is underrated permanently, because the AI flying it never finds the
    line. This bounds what the whole method can mean, and no sample size
    touches it.

The implementation is coordinate descent over sparse binary columns — one sweep
costs the number of (deck, card) incidences, so a thousand decks of ninety-nine
cards is a hundred thousand operations per sweep and needs no numpy.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Sequence

DEFAULT_ALPHA = 50.0
"""Prior strength in units of games: a card seen in `alpha` games' worth of
decks is pulled halfway to zero. Prefer `cross_validated_alpha`."""


@dataclass(frozen=True)
class Rating:
    card: str
    coefficient: float
    """Estimated change in win rate from including this card, shrunk."""
    support: int
    """Decks containing it. Low support means the estimate is mostly prior."""
    games: float
    standard_error: float
    """Approximate: sqrt(residual variance / (weight + alpha)). Ridge makes
    this optimistic — it ignores the bias the penalty introduces."""

    @property
    def z(self) -> float:
        return self.coefficient / self.standard_error if self.standard_error else 0.0


@dataclass
class _Fit:
    intercept: float
    coefficients: dict[str, float]
    table_effects: dict[str, float]
    residual_variance: float
    weight: dict[str, float]
    support: dict[str, int]


def _fit(rows: Sequence[tuple[Sequence[str], str, int, float]], alpha: float,
         sweeps: int, tol: float) -> _Fit:
    features: dict[str, int] = {}
    tables: dict[str, int] = {}
    row_cols: list[list[int]] = []
    row_table: list[int] = []
    weights: list[float] = []
    targets: list[float] = []

    for cards, label, games, wins in rows:
        if games <= 0:
            continue
        cols = []
        for name in dict.fromkeys(cards):
            cols.append(features.setdefault(name, len(features)))
        row_cols.append(cols)
        row_table.append(tables.setdefault(label, len(tables)))
        weights.append(float(games))
        targets.append(wins / games)

    n_rows = len(row_cols)
    if not n_rows:
        return _Fit(0.0, {}, {}, 0.0, {}, {})

    col_rows: list[list[int]] = [[] for _ in features]
    for i, cols in enumerate(row_cols):
        for j in cols:
            col_rows[j].append(i)
    table_rows: list[list[int]] = [[] for _ in tables]
    for i, t in enumerate(row_table):
        table_rows[t].append(i)

    col_weight = [sum(weights[i] for i in rs) for rs in col_rows]
    table_weight = [sum(weights[i] for i in rs) for rs in table_rows]
    total_weight = sum(weights)

    beta = [0.0] * len(features)
    theta = [0.0] * len(tables)
    intercept = sum(w * y for w, y in zip(weights, targets)) / total_weight
    residual = [targets[i] - intercept for i in range(n_rows)]

    for _ in range(sweeps):
        shift = 0.0

        update = sum(weights[i] * residual[i] for i in range(n_rows)) / total_weight
        intercept += update
        for i in range(n_rows):
            residual[i] -= update
        shift = max(shift, abs(update))

        for t, rs in enumerate(table_rows):          # unpenalised nuisance terms
            if not rs:
                continue
            num = sum(weights[i] * (residual[i] + theta[t]) for i in rs)
            new = num / table_weight[t]
            delta = new - theta[t]
            if delta:
                for i in rs:
                    residual[i] -= delta
                theta[t] = new
                shift = max(shift, abs(delta))

        for j, rs in enumerate(col_rows):
            if not rs:
                continue
            num = sum(weights[i] * (residual[i] + beta[j]) for i in rs)
            new = num / (col_weight[j] + alpha)
            delta = new - beta[j]
            if delta:
                for i in rs:
                    residual[i] -= delta
                beta[j] = new
                shift = max(shift, abs(delta))

        if shift < tol:
            break

    dof = max(n_rows - 1, 1)
    variance = sum(weights[i] * residual[i] ** 2 for i in range(n_rows)) / (
        total_weight / n_rows * dof)
    return _Fit(
        intercept=intercept,
        coefficients={name: beta[j] for name, j in features.items()},
        table_effects={label: theta[t] for label, t in tables.items()},
        residual_variance=variance,
        weight={name: col_weight[j] for name, j in features.items()},
        support={name: len(col_rows[j]) for name, j in features.items()},
    )


def card_ratings(rows: Sequence[tuple[Sequence[str], str, int, float]], *,
                 alpha: float = DEFAULT_ALPHA, sweeps: int = 200,
                 tol: float = 1e-9, min_support: int = 1) -> list[Rating]:
    """Rate every card, best first. Rows are (cards, table_label, games, wins)."""
    fit = _fit(rows, alpha, sweeps, tol)
    out = []
    for name, coefficient in fit.coefficients.items():
        support = fit.support[name]
        if support < min_support:
            continue
        weight = fit.weight[name]
        se = (fit.residual_variance / (weight + alpha)) ** 0.5
        out.append(Rating(name, coefficient, support, weight, se))
    return sorted(out, key=lambda r: -r.coefficient)


def cross_validated_alpha(rows: Sequence[tuple[Sequence[str], str, int, float]],
                          candidates: Sequence[float] = (10, 25, 50, 100, 250, 500),
                          *, folds: int = 5, seed: int = 0) -> float:
    """Pick the penalty by held-out weighted squared error, not by taste."""
    indexed = list(rows)
    rng = random.Random(seed)
    order = list(range(len(indexed)))
    rng.shuffle(order)
    assignment = {i: k % folds for k, i in enumerate(order)}

    best, best_error = candidates[0], float("inf")
    for alpha in candidates:
        error = weight = 0.0
        for fold in range(folds):
            train = [indexed[i] for i in order if assignment[i] != fold]
            test = [indexed[i] for i in order if assignment[i] == fold]
            if not train or not test:
                continue
            fit = _fit(train, alpha, sweeps=200, tol=1e-9)
            for cards, label, games, wins in test:
                if games <= 0:
                    continue
                predicted = fit.intercept + fit.table_effects.get(label, 0.0)
                predicted += sum(fit.coefficients.get(name, 0.0)
                                 for name in dict.fromkeys(cards))
                error += games * (wins / games - predicted) ** 2
                weight += games
        if weight and error / weight < best_error:
            best, best_error = alpha, error / weight
    return best
