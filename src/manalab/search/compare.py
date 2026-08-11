"""Deciding whether one deck actually beats another.

Every A-vs-B claim this repo makes should come from here, because the obvious
way to compare two decks — take the difference of their means and look at the
standard errors — throws away most of the information when the decks were
measured on a shared stream.

Under common random numbers the per-game outcomes are strongly correlated, so
the *difference* has variance `2σ²(1-ρ)` rather than `2σ²`. At ρ = 0.9 that is a
tenfold reduction in the variance of the thing you actually care about, and it
is invisible to anyone comparing summary statistics.

The catch, stated plainly: CRN buys precision on the *difference*, not on either
deck's absolute score. It also cannot be applied across decks measured on
different streams — `paired()` raises rather than silently degrading.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from statistics import NormalDist
from typing import Sequence

Vector = tuple[int, ...]
_NORMAL = NormalDist()


@dataclass(frozen=True)
class Comparison:
    """The result of asking "is A better than B?"."""

    n: int
    mean_diff: float
    """Mean of (A - B). Positive means A scored higher."""
    stderr: float
    correlation: float
    """Realized per-game correlation between the two decks. This is the CRN
    coupling actually achieved, not the one assumed."""
    paired: bool

    @property
    def z(self) -> float:
        return self.mean_diff / self.stderr if self.stderr > 0 else 0.0

    @property
    def p_value(self) -> float:
        """Two-sided, normal approximation. Valid at the sample sizes used here
        (hundreds to millions of games); would need a t-distribution below ~30."""
        return 2 * (1 - _NORMAL.cdf(abs(self.z)))

    def ci95(self) -> tuple[float, float]:
        return (self.mean_diff - 1.96 * self.stderr, self.mean_diff + 1.96 * self.stderr)

    def verdict(self, alpha: float = 0.05) -> int:
        """+1 if A wins, -1 if B wins, 0 if undecided at this sample size.

        Returning 0 rather than guessing is the point: a hill climber that
        accepts every positive-looking difference will happily wander uphill on
        noise, and on a 1-swap neighbourhood most differences are noise.
        """
        if self.stderr == 0.0:
            return 0
        if self.p_value >= alpha:
            return 0
        return 1 if self.mean_diff > 0 else -1

    @property
    def variance_reduction(self) -> float:
        """How many times more games an unpaired comparison would need.

        `1/(1-ρ)` under equal variances. Exactly 1.0 when the streams are
        independent, which is the honest answer for an unpaired comparison.
        """
        if not self.paired:
            return 1.0
        rho = min(max(self.correlation, -0.999999), 0.999999)
        return 1.0 / (1.0 - rho)


def paired(a: Sequence[float], b: Sequence[float]) -> Comparison:
    """Compare two decks measured game-for-game on the same stream.

    Requires equal-length sample vectors aligned by game index. Misaligning them
    would quietly turn a paired test into an unpaired one with a paired test's
    (too small) standard error, which is worse than not pairing at all.
    """
    if len(a) != len(b):
        raise ValueError(
            f"paired comparison needs aligned samples, got {len(a)} and {len(b)}; "
            "were these measured on the same stream?"
        )
    if len(a) < 2:
        raise ValueError("need at least two games")

    diffs = [x - y for x, y in zip(a, b)]
    n = len(diffs)
    mean = statistics.fmean(diffs)
    sd = statistics.stdev(diffs)

    return Comparison(
        n=n,
        mean_diff=mean,
        stderr=sd / n**0.5,
        correlation=_correlation(a, b),
        paired=True,
    )


def unpaired(a: Sequence[float], b: Sequence[float]) -> Comparison:
    """Welch comparison of two independently measured decks. The baseline that
    pairing is supposed to beat."""
    if len(a) < 2 or len(b) < 2:
        raise ValueError("need at least two games per deck")

    va, vb = statistics.variance(a), statistics.variance(b)
    stderr = (va / len(a) + vb / len(b)) ** 0.5

    return Comparison(
        n=min(len(a), len(b)),
        mean_diff=statistics.fmean(a) - statistics.fmean(b),
        stderr=stderr,
        correlation=0.0,
        paired=False,
    )


def games_needed(effect: float, sd: float, *, alpha: float = 0.05, power: float = 0.8) -> int:
    """Games per deck to detect `effect` at the given power. Run this *before*
    an experiment, not after: an underpowered comparison that comes back
    non-significant is indistinguishable from no effect.

    For a paired test, pass the standard deviation of the *difference*, which
    with CRN is far smaller than either deck's own standard deviation.
    """
    if effect <= 0 or sd <= 0:
        raise ValueError("effect and sd must be positive")
    z_alpha = _NORMAL.inv_cdf(1 - alpha / 2)
    z_beta = _NORMAL.inv_cdf(power)
    return int(((z_alpha + z_beta) * sd / effect) ** 2) + 1


def _correlation(a: Sequence[float], b: Sequence[float]) -> float:
    try:
        return statistics.correlation(a, b)
    except statistics.StatisticsError:
        # Constant samples — every game identical. No linear relationship exists.
        return 0.0
