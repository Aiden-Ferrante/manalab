"""Co-evolution: game theory on hand-built matrices, and the loop against a fake.

Everything here runs without a game. That is the point of the `Arena` seam — the
tournament logic is where co-evolution goes wrong, so it has to be testable on
matrices whose right answer is known by hand rather than on simulated Magic.
"""

from __future__ import annotations

import random

import pytest

from manalab.search.coevolve import (
    Archive,
    Champion,
    coevolve,
    cycles,
    nash,
    payoff_matrix,
    score_against_mixture,
)


def champ(label: str, population: str = "p", round: int = 1) -> Champion:
    return Champion(label=label, population=population, round=round, counts={})


# --- nash ---------------------------------------------------------------


def test_a_dominant_deck_takes_the_whole_mixture() -> None:
    # A beats B and C outright; the equilibrium is to just play A.
    matrix = [[0.5, 0.9, 0.9], [0.1, 0.5, 0.5], [0.1, 0.5, 0.5]]
    mixture = nash(matrix)
    assert mixture[0] == pytest.approx(1.0, abs=0.02)


def test_rock_paper_scissors_is_a_third_each() -> None:
    """The case a single 'best deck' cannot describe."""
    matrix = [[0.5, 1.0, 0.0], [0.0, 0.5, 1.0], [1.0, 0.0, 0.5]]
    mixture = nash(matrix)
    for weight in mixture:
        assert weight == pytest.approx(1 / 3, abs=0.03)


def test_a_mirror_field_is_uniform_enough_to_be_meaningless() -> None:
    matrix = [[0.5] * 3 for _ in range(3)]
    assert sum(nash(matrix)) == pytest.approx(1.0)


def test_mixture_is_a_probability_distribution() -> None:
    rng = random.Random(0)
    n = 6
    matrix = [[0.5] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            value = rng.random()
            matrix[i][j], matrix[j][i] = value, 1.0 - value
    mixture = nash(matrix)
    assert sum(mixture) == pytest.approx(1.0)
    assert all(w >= 0 for w in mixture)


def test_nash_handles_degenerate_sizes() -> None:
    assert nash([]) == []
    assert nash([[0.5]]) == [1.0]


# --- cycles -------------------------------------------------------------


def test_rock_paper_scissors_is_detected() -> None:
    matrix = [[0.5, 1.0, 0.0], [0.0, 0.5, 1.0], [1.0, 0.0, 0.5]]
    found = cycles(matrix, ["rock", "paper", "scissors"])
    assert len(found) == 1


def test_a_transitive_field_has_no_cycles() -> None:
    matrix = [[0.5, 0.8, 0.9], [0.2, 0.5, 0.8], [0.1, 0.2, 0.5]]
    assert cycles(matrix, ["a", "b", "c"]) == []


def test_coin_flips_are_not_read_as_cycles() -> None:
    """Without a margin, a matrix of near-0.5s reports cycles everywhere."""
    matrix = [[0.5, 0.505, 0.495], [0.495, 0.5, 0.505], [0.505, 0.495, 0.5]]
    assert cycles(matrix, ["a", "b", "c"]) == []


def test_a_cycle_is_reported_once_not_three_times() -> None:
    matrix = [[0.5, 1.0, 0.0], [0.0, 0.5, 1.0], [1.0, 0.0, 0.5]]
    assert len(cycles(matrix, ["a", "b", "c"])) == 1


# --- the archive --------------------------------------------------------


def test_opponents_include_other_populations_not_your_own() -> None:
    archive = Archive()
    for population in ("red", "blue", "green"):
        archive.add(champ(f"{population}-r1", population))

    chosen = archive.opponents_for("red", random.Random(0), n_recent=4, n_historic=0)
    assert all(c.population != "red" for c in chosen)
    assert {c.population for c in chosen} == {"blue", "green"}


def test_the_hall_of_fame_reaches_back_past_the_current_round() -> None:
    """The fix for evolutionary forgetting. Without it a run can walk in circles."""
    archive = Archive()
    for round_index in (1, 2, 3):
        for population in ("red", "blue"):
            archive.add(champ(f"{population}-r{round_index}", population, round_index))

    chosen = archive.opponents_for("red", random.Random(1), n_recent=1, n_historic=3)
    assert any(c.round < 3 for c in chosen), "only the newest opponents were sampled"


def test_latest_returns_the_most_recent_for_a_population() -> None:
    archive = Archive()
    archive.add(champ("red-r1", "red", 1))
    archive.add(champ("red-r2", "red", 2))
    assert archive.latest("red").label == "red-r2"
    assert archive.latest("blue") is None


def test_an_empty_archive_offers_no_opponents() -> None:
    assert Archive().opponents_for("red", random.Random(0)) == []


# --- the payoff matrix --------------------------------------------------


class FakeArena:
    """Deck strength is a number; win rate is a logistic-ish function of the gap."""

    def __init__(self, strengths):
        self.strengths = strengths
        self.calls = 0

    def payoff(self, a, b, *, n_games, seed):
        self.calls += 1
        gap = self.strengths[a.label] - self.strengths[b.label]
        return min(1.0, max(0.0, 0.5 + gap / 10.0))

    def problem_for(self, population, opponents):  # pragma: no cover
        raise NotImplementedError

    def to_champion(self, population, round, vector, score):  # pragma: no cover
        raise NotImplementedError


def test_the_matrix_is_antisymmetric() -> None:
    arena = FakeArena({"a": 0.0, "b": 2.0, "c": 5.0})
    field = [champ("a"), champ("b"), champ("c")]
    matrix = payoff_matrix(arena, field, n_games=10, seed=0)

    for i in range(3):
        assert matrix[i][i] == 0.5
        for j in range(3):
            assert matrix[i][j] + matrix[j][i] == pytest.approx(1.0)


def test_only_the_upper_triangle_is_simulated() -> None:
    arena = FakeArena({"a": 0.0, "b": 1.0, "c": 2.0, "d": 3.0})
    field = [champ(n) for n in "abcd"]
    payoff_matrix(arena, field, n_games=10, seed=0)
    assert arena.calls == 6, "a 4-deck round robin is 6 pairings, not 16"


def test_scoring_against_a_mixture_weights_by_share() -> None:
    arena = FakeArena({"me": 5.0, "weak": 0.0, "strong": 10.0})
    field = [champ("weak"), champ("strong")]
    only_weak = score_against_mixture(arena, champ("me"), field, [1.0, 0.0],
                                      n_games=10, seed=0)
    only_strong = score_against_mixture(arena, champ("me"), field, [0.0, 1.0],
                                        n_games=10, seed=0)
    assert only_weak > 0.5 > only_strong


def test_scoring_against_an_empty_field_is_even() -> None:
    arena = FakeArena({"me": 1.0})
    assert score_against_mixture(arena, champ("me"), [], [], n_games=10, seed=0) == 0.5


# --- the loop -----------------------------------------------------------


class LoopArena(FakeArena):
    """Each round, every population gets a little stronger."""

    def __init__(self):
        super().__init__({})

    def problem_for(self, population, opponents):
        return ("problem", population, tuple(c.label for c in opponents))

    def to_champion(self, population, round, vector, score):
        label = f"{population}-r{round}"
        self.strengths[label] = float(round)
        return Champion(label=label, population=population, round=round,
                        counts={}, vector=tuple(vector), score=score)


def run_coevolution(rounds=3, populations=("red", "blue")):
    arena = LoopArena()
    return arena, coevolve(
        arena,
        populations,
        optimizer_factory=lambda population, round: ("opt", population),
        runner=lambda problem, optimizer, seed: ((1, 2, 3), 0.7),
        rounds=rounds,
        matrix_games=10,
        progress_games=10,
    )


def test_every_population_produces_a_champion_every_round() -> None:
    _, result = run_coevolution(rounds=3, populations=("red", "blue"))
    assert len(result.archive) == 6
    assert len(result.rounds) == 3
    assert {c.population for c in result.final.champions} == {"red", "blue"}


def test_the_matrix_grows_with_the_archive() -> None:
    _, result = run_coevolution(rounds=3)
    assert [len(r.matrix) for r in result.rounds] == [2, 4, 6]


def test_the_first_round_reports_no_progress() -> None:
    """There is nothing to have made progress against yet."""
    _, result = run_coevolution(rounds=2)
    assert result.rounds[0].progress == {}
    assert result.rounds[1].progress


def test_improving_populations_beat_the_previous_field() -> None:
    _, result = run_coevolution(rounds=3)
    for score in result.rounds[-1].progress.values():
        assert score > 0.5


def test_opponents_are_drawn_from_the_archive_after_round_one() -> None:
    arena, result = run_coevolution(rounds=2)
    assert len(result.archive) == 4
    assert all(c.vector == (1, 2, 3) for c in result.archive)


def test_the_archive_refuses_a_duplicate_label() -> None:
    """A label collision is silent and corrupting, not cosmetic.

    `score_against_mixture` treats a same-label opponent as a mirror and scores
    it 0.5 without playing it, so two populations sharing a label skip each
    other's decks entirely. This happened for real: "black" and "blue" both
    abbreviated to B, and blue was reported as surviving in an equilibrium it
    held zero weight in.
    """
    archive = Archive()
    archive.add(champ("B1", "black"))
    with pytest.raises(ValueError, match="duplicate"):
        archive.add(champ("B1", "blue"))


def test_wubrg_codes_do_not_collide() -> None:
    codes = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}
    archive = Archive()
    for population, code in codes.items():
        archive.add(champ(f"{code}1", population))
    assert len(archive) == 5
