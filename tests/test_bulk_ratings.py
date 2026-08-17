"""The bulk method's three pieces: sampling, running, estimating."""

from __future__ import annotations

import random

import pytest

from manalab.evaluate.bulk import BulkDeck, Table, run_bulk, summarise, training_rows
from manalab.evaluate.result import EvalResult
from manalab.search.ratings import card_ratings, cross_validated_alpha
from manalab.search.sampler import CurveTemplate, sample_deck, sample_many

POOL = {cmc: [f"c{cmc}_{i}" for i in range(40)] for cmc in range(1, 8)}
TEMPLATE = CurveTemplate(lands=38, quota={1: 6, 2: 13, 3: 13, 4: 10, 5: 8, 6: 6, 7: 5})


def test_template_must_hold_ninety_nine():
    with pytest.raises(ValueError, match="99"):
        CurveTemplate(lands=38, quota={1: 5})


def test_sampled_deck_matches_the_template():
    deck = sample_deck(POOL, TEMPLATE, random.Random(1))
    assert len(deck) == TEMPLATE.nonland == 61
    assert len(set(deck)) == len(deck), "singleton"
    for cmc, want in TEMPLATE.quota.items():
        assert sum(1 for n in deck if n.startswith(f"c{cmc}_")) == want


def test_core_cards_vary_between_decks():
    """The whole point: a card in every deck has no contrast to estimate."""
    core = ["c1_0", "c2_0", "c3_0"]
    buckets = {"c1_0": 1, "c2_0": 2, "c3_0": 3}
    rng = random.Random(7)
    seen = [sum(1 for c in core if c in sample_deck(
        POOL, TEMPLATE, rng, core=core, core_prob=0.5, core_bucket=buckets))
        for _ in range(40)]
    assert 0 < sum(seen) < 40 * len(core), "core inclusion must be random"


def test_pool_too_small_is_an_error_not_a_short_deck():
    with pytest.raises(ValueError, match="pool holds"):
        sample_deck({1: ["a", "b"]}, CurveTemplate(lands=38, quota={1: 61}),
                    random.Random(0))


def test_sample_many_returns_distinct_decks():
    decks = sample_many(POOL, TEMPLATE, 25, seed=3)
    assert len(decks) == len(set(decks)) == 25


def test_ratings_recover_known_effects():
    """Synthetic ground truth: five good cards, five bad, the rest inert.

    If the estimator cannot separate a 10-point effect from noise on data it
    generated itself, nothing it says about Forge games is worth reading.
    """
    rng = random.Random(11)
    good = {f"c1_{i}" for i in range(3)} | {f"c2_{i}" for i in range(2)}
    bad = {f"c6_{i}" for i in range(3)} | {f"c7_{i}" for i in range(2)}
    rows = []
    # 0.06 per card: with ~90 decks carrying each card at 8 games apiece the
    # coefficient noise floor is ~0.016, so this is a z of ~3.7. An earlier
    # version of this test used 0.02 (z~1.2) and failed correctly — the
    # estimator cannot see an effect the design cannot resolve.
    for deck in sample_many(POOL, TEMPLATE, 600, seed=5):
        p = 0.25 + 0.06 * sum(c in good for c in deck)
        p -= 0.06 * sum(c in bad for c in deck)
        games = 8
        wins = sum(rng.random() < max(0.01, min(0.99, p)) for _ in range(games))
        rows.append((list(deck), "t0", games, float(wins)))

    ratings = card_ratings(rows, alpha=20.0)
    ranked = [r.card for r in ratings]
    top, bottom = set(ranked[:10]), set(ranked[-10:])
    assert len(good & top) >= 4, f"good cards not at the top: {ranked[:10]}"
    assert len(bad & bottom) >= 4, f"bad cards not at the bottom: {ranked[-10:]}"


def test_table_effects_absorb_a_confounded_matchup():
    """A card that mostly faced the brutal table must not be blamed for it.

    Random table assignment cannot test this — there would be nothing to leak.
    So the confound is built in: decks holding `victim` go to the brutal table
    80% of the time, and the card itself does nothing. Modelling the table has
    to clear it; collapsing the tables into one label has to convict it. The
    contrast between those two fits is the actual claim.
    """
    rng = random.Random(2)
    victim = "c1_0"
    rows = []
    for deck in sample_many(POOL, TEMPLATE, 400, seed=9):
        brutal = rng.random() < (0.8 if victim in deck else 0.2)
        label = "brutal" if brutal else "easy"
        p = 0.05 if brutal else 0.45
        wins = sum(rng.random() < p for _ in range(8))
        rows.append((list(deck), label, 8, float(wins)))

    modelled = {r.card: r.coefficient for r in card_ratings(rows, alpha=20.0)}
    collapsed = {r.card: r.coefficient for r in
                 card_ratings([(c, "all", g, w) for c, _, g, w in rows], alpha=20.0)}
    assert collapsed[victim] < -0.10, "the confounded fit should convict it"
    assert abs(modelled[victim]) < abs(collapsed[victim]) / 3, (
        f"table term failed to absorb the confound: modelled "
        f"{modelled[victim]:.3f} vs collapsed {collapsed[victim]:.3f}")


def test_cross_validated_alpha_prefers_shrinkage_on_pure_noise():
    rng = random.Random(4)
    rows = [(list(d), "t0", 8, float(sum(rng.random() < 0.25 for _ in range(8))))
            for d in sample_many(POOL, TEMPLATE, 200, seed=13)]
    assert cross_validated_alpha(rows, (10, 500)) == 500


class _FakeEvaluator:
    """Deterministic stand-in: wins depend on one card, so rows are checkable."""

    def __init__(self, opponents):
        self.opponents = opponents

    def evaluate(self, deck_name, commander, counts, *, n_games, seed):
        wins = tuple(1.0 if "good" in counts else 0.0 for _ in range(n_games))
        return EvalResult(deck_name=deck_name, evaluator="fake", n_games=n_games,
                          seed=seed, metrics={"win_rate": sum(wins) / n_games},
                          samples={"win_rate": wins})


def _decks():
    return [BulkDeck("d0", "General", {"good": 1, "Forest": 38}),
            BulkDeck("d1", "General", {"meh": 1, "Forest": 38})]


def test_run_bulk_stores_rows_and_resumes(tmp_path):
    db = tmp_path / "bulk.sqlite"
    tables = [Table("t0", (("o", "G", {"Plains": 40}),) * 3)]
    added = run_bulk(_decks(), tables, games=4, seed=1, db_path=db,
                     max_workers=2, evaluator_factory=_FakeEvaluator)
    assert added == 8

    again = run_bulk(_decks(), tables, games=4, seed=1, db_path=db,
                     max_workers=2, evaluator_factory=_FakeEvaluator)
    assert again == 0, "stored pairings must not be replayed"

    rows = training_rows(db)
    assert len(rows) == 2
    by_card = {tuple(cards): wins for cards, _, _, wins in rows}
    assert by_card[("good",)] == 4.0 and by_card[("meh",)] == 0.0
    assert "Forest" not in {c for cards, _, _, _ in rows for c in cards}
    assert "2 pairings, 8 games" in summarise(rows)
