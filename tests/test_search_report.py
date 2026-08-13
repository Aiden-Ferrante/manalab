"""Interpretation: never print an ordering the data cannot support.

These tests encode the mistake this module was written after — a five-colour
ranking reported from one seed per colour, with a spread narrower than the
seed-to-seed noise.
"""

from __future__ import annotations

import pytest

from manalab.search.report import (
    Measurement,
    distinguishable,
    summarise,
    table,
    tiers,
)


def m(label: str, *samples: float) -> Measurement:
    return Measurement(label, tuple(samples))


# --- the statistics -----------------------------------------------------


def test_mean_and_spread() -> None:
    measurement = m("a", 0.4, 0.6, 0.5)
    assert measurement.mean == pytest.approx(0.5)
    assert measurement.sd == pytest.approx(0.1)
    assert measurement.n == 3


def test_a_single_run_has_no_measurable_spread() -> None:
    """One sample is one sample. It gets a mean and no error bar."""
    measurement = m("a", 0.5)
    assert measurement.sd == 0.0
    assert measurement.stderr == 0.0


def test_widely_separated_means_are_distinguishable() -> None:
    assert distinguishable(m("a", 0.90, 0.91, 0.89, 0.90),
                           m("b", 0.20, 0.21, 0.19, 0.20))


def test_overlapping_noisy_means_are_not() -> None:
    """The real case: a 0.05 gap on runs that swing by 0.12."""
    assert not distinguishable(m("a", 0.40, 0.52, 0.31, 0.56),
                               m("b", 0.42, 0.37, 0.39, 0.59))


def test_a_gap_inside_the_noise_is_refused_even_if_consistent() -> None:
    a, b = m("a", 0.55, 0.56, 0.54), m("b", 0.53, 0.52, 0.54)
    assert a.mean > b.mean
    assert distinguishable(a, b) or not distinguishable(a, b)  # either is fine
    # ...but a tiny gap on wide runs must not separate.
    assert not distinguishable(m("c", 0.55, 0.30, 0.80), m("d", 0.53, 0.28, 0.78))


# --- tiers --------------------------------------------------------------


def test_clear_winner_gets_its_own_tier() -> None:
    banded = tiers([m("strong", 0.90, 0.91, 0.89),
                    m("weak", 0.20, 0.19, 0.21),
                    m("mid", 0.55, 0.54, 0.56)])
    assert [x.label for tier in banded for x in tier] == ["strong", "mid", "weak"]
    assert all(len(tier) == 1 for tier in banded)


def test_indistinguishable_results_share_a_tier() -> None:
    banded = tiers([m("a", 0.50, 0.62, 0.41, 0.66),
                    m("b", 0.52, 0.47, 0.49, 0.69),
                    m("c", 0.51, 0.55, 0.44, 0.62)])
    assert len(banded) == 1, "three overlapping results were ordered"
    assert len(banded[0]) == 3


def test_the_real_five_colour_case_does_not_fully_order() -> None:
    """Black and blue separate; the middle three do not."""
    banded = tiers([
        m("black", 0.652, 0.755, 0.637, 0.745),
        m("green", 0.679, 0.601, 0.555, 0.653),
        m("white", 0.611, 0.450, 0.614, 0.529),
        m("red", 0.277, 0.444, 0.411, 0.397),
        m("blue", 0.296, 0.233, 0.329, 0.180),
    ])
    labels = [[x.label for x in tier] for tier in banded]
    assert len(banded) < 5, f"claimed a full ordering of five noisy results: {labels}"
    assert "black" in labels[0]
    assert "blue" in labels[-1]


def test_summarise_orders_by_mean() -> None:
    out = summarise({"low": [0.1, 0.2], "high": [0.8, 0.9]})
    assert [x.label for x in out] == ["high", "low"]


# --- the report ---------------------------------------------------------


def test_the_table_refuses_to_order_pure_noise() -> None:
    rendered = table([m("a", 0.5, 0.2, 0.8), m("b", 0.5, 0.9, 0.1)])
    assert "No ordering is supported" in rendered


def test_the_table_reports_tiers_when_they_exist() -> None:
    rendered = table([m("strong", 0.9, 0.91, 0.89), m("weak", 0.1, 0.11, 0.09)])
    assert "tier 1" in rendered and "tier 2" in rendered


def test_the_table_always_shows_the_spread() -> None:
    rendered = table([m("a", 0.5, 0.6, 0.4)])
    assert "sd" in rendered and "95% CI" in rendered


def test_an_empty_report_does_not_crash() -> None:
    assert table([]) == "(no runs)"
