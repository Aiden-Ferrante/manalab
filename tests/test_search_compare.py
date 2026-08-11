"""Phase 2: paired comparison.

These use synthetic samples with known correlation rather than the simulator, so
a failure points at the statistics rather than at the game model.
"""

from __future__ import annotations

import random

import pytest

from manalab.search.compare import Comparison, games_needed, paired, unpaired


def correlated(n: int, rho: float, shift: float, seed: int) -> tuple[list[float], list[float]]:
    """Two unit-variance samples with correlation exactly `rho`, B shifted down.

    Weights are sqrt(rho) and sqrt(1-rho), *not* rho and sqrt(1-rho**2) — the
    latter is the tempting form and yields correlation rho**2, which quietly
    makes every variance-reduction assertion below wrong.
    """
    if not 0.0 <= rho < 1.0:
        raise ValueError("rho must be in [0, 1)")
    rng = random.Random(seed)
    w_shared, w_own = rho**0.5, (1 - rho) ** 0.5

    a: list[float] = []
    b: list[float] = []
    for _ in range(n):
        shared = rng.gauss(0, 1)
        a.append(w_shared * shared + w_own * rng.gauss(0, 1))
        b.append(w_shared * shared + w_own * rng.gauss(0, 1) - shift)
    return a, b


def test_paired_recovers_the_true_difference() -> None:
    a, b = correlated(20_000, rho=0.9, shift=0.05, seed=1)
    result = paired(a, b)
    lo, hi = result.ci95()
    assert lo < 0.05 < hi


def test_paired_detects_correlation_that_unpaired_ignores() -> None:
    a, b = correlated(20_000, rho=0.9, shift=0.05, seed=2)
    assert paired(a, b).correlation == pytest.approx(0.9, abs=0.02)
    assert unpaired(a, b).correlation == 0.0


def test_pairing_shrinks_the_standard_error() -> None:
    """The whole justification for common random numbers."""
    a, b = correlated(20_000, rho=0.9, shift=0.05, seed=3)
    p, u = paired(a, b), unpaired(a, b)

    assert p.stderr < u.stderr / 2
    # 1/(1-rho) = 10x fewer games for the same precision.
    assert p.variance_reduction == pytest.approx(10.0, rel=0.25)
    assert u.variance_reduction == 1.0


def test_pairing_finds_an_effect_unpaired_misses() -> None:
    """A small effect under strong correlation: significant when paired,
    invisible when not. This is the case the benchmark lives in."""
    a, b = correlated(2_000, rho=0.97, shift=0.03, seed=4)
    assert paired(a, b).verdict() == 1
    assert unpaired(a, b).verdict() == 0


def test_verdict_abstains_when_there_is_no_effect() -> None:
    """Returning 0 rather than guessing keeps hill climbers from walking uphill
    on noise, which on a 1-swap neighbourhood is most of what is available."""
    a, b = correlated(5_000, rho=0.9, shift=0.0, seed=5)
    assert paired(a, b).verdict() == 0


def test_verdict_direction() -> None:
    a, b = correlated(20_000, rho=0.9, shift=0.05, seed=6)
    assert paired(a, b).verdict() == 1
    assert paired(b, a).verdict() == -1


def test_misaligned_samples_raise_rather_than_degrade() -> None:
    """Silently treating unaligned samples as paired would apply a paired
    standard error to an unpaired difference — worse than never pairing."""
    a, b = correlated(100, rho=0.9, shift=0.0, seed=7)
    with pytest.raises(ValueError, match="same stream"):
        paired(a, b[:50])


def test_constant_samples_do_not_blow_up() -> None:
    result = paired([1.0] * 50, [1.0] * 50)
    assert result.stderr == 0.0
    assert result.verdict() == 0
    assert result.p_value == pytest.approx(1.0)


# --- power -------------------------------------------------------------


def test_games_needed_scales_with_the_inverse_square_of_the_effect() -> None:
    big = games_needed(0.02, sd=0.5)
    small = games_needed(0.01, sd=0.5)
    assert small == pytest.approx(4 * big, rel=0.01)


def test_games_needed_matches_the_textbook_constant() -> None:
    """n = ((1.96 + 0.84) * sd / effect)^2 ~= 7.85 * (sd/effect)^2."""
    n = games_needed(0.1, sd=1.0)
    assert n == pytest.approx(785, rel=0.02)


def test_power_analysis_agrees_with_an_actual_test() -> None:
    """Sizing an experiment is only useful if the size is right: at the
    prescribed n, a real paired test should detect the effect most of the time."""
    rho, shift, sd_diff = 0.9, 0.05, (2 * (1 - 0.9)) ** 0.5
    n = games_needed(shift, sd=sd_diff, power=0.8)

    detected = sum(
        paired(*correlated(n, rho=rho, shift=shift, seed=100 + trial)).verdict() == 1
        for trial in range(40)
    )
    assert detected >= 26  # 80% power, allowing for 40-trial sampling noise
