"""Co-evolution: populations that optimise against each other rather than a fixture.

A fixed gauntlet asks "how good is this deck against a world that never changes".
Co-evolution asks the harder and more realistic question — "how good is this deck
against opponents that are also improving" — and it is much easier to get wrong,
because every naive version produces a rising fitness curve whether or not
anything is improving. Three failure modes, and what this module does about each:

**Cycling.** A beats B beats C beats A. Every population reports progress every
round and the set as a whole goes in a circle forever. Detected explicitly by
`cycles()`; a metagame with intransitive triples is interesting, and one whose
"winner" changes every round while the cycles persist is *not* converging.

**Forgetting.** Round-5 black beats round-4 green and loses to round-1 green.
Optimising against only the current opponents lets a population walk in a loop
through strategy space, rediscovering what it already discarded. The fix is a
**hall of fame**: opponents are sampled from every champion ever produced, not
just the newest ones (Rosin & Belew's archive idea).

**A moving objective.** Win rate against round 3's field is not comparable to win
rate against round 1's field, so the headline number stops meaning anything
across rounds. The fix is to score progress against a *fixed reference*: the
Nash mixture of the previous round's archive. `progress()` reports that, and it
is the only number here that may honestly be compared across rounds.

The tournament logic lives here; nothing in this module knows what a card is.
Building a deck and playing a match are delegated to an `Arena`, which the caller
supplies — that is what keeps `search` free of game knowledge, and it means the
same co-evolution driver works over any evaluator.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Mapping, Protocol, Sequence, runtime_checkable

from manalab.search.problem import Problem

__all__ = [
    "Archive",
    "Arena",
    "Champion",
    "CoevolutionResult",
    "RoundReport",
    "coevolve",
    "cycles",
    "nash",
    "payoff_matrix",
]


@dataclass(frozen=True)
class Champion:
    """One population's best deck at one round.

    Carries `counts` (card name -> copies) rather than the raw vector, because a
    vector is only meaningful against the pool it was searched over and these
    decks have to face populations built from different pools.
    """

    label: str
    population: str
    round: int
    counts: Mapping[str, int]
    vector: tuple[int, ...] = ()
    score: float = 0.0
    """Win rate against the opponents it was trained on. Not comparable across rounds."""

    def __hash__(self) -> int:
        return hash((self.label, self.population, self.round))


@runtime_checkable
class Arena(Protocol):
    """Everything co-evolution needs from the game, and nothing more."""

    def problem_for(
        self, population: str, opponents: Sequence[Champion]
    ) -> Problem:
        """A search problem: this population's pool, scored against `opponents`."""

    def payoff(self, a: Champion, b: Champion, *, n_games: int, seed: int) -> float:
        """`a`'s win rate against `b`. Draws count as half."""

    def to_champion(
        self, population: str, round: int, vector: Sequence[int], score: float
    ) -> Champion:
        """Turn a search result into an archivable champion."""


@dataclass
class Archive:
    """Every champion ever produced. The thing new decks are measured against."""

    champions: list[Champion] = field(default_factory=list)

    def add(self, champion: Champion) -> None:
        """Append a champion. Labels must be unique, and that is load-bearing.

        A duplicate label is silent and corrupting rather than cosmetic:
        `score_against_mixture` treats a same-label opponent as a mirror and
        scores it 0.5 without playing the match, so two populations sharing a
        label quietly skip each other. Caught in a real run where "black" and
        "blue" both abbreviated to B, which also reported blue as surviving in
        an equilibrium it had zero weight in.
        """
        existing = {c.label for c in self.champions}
        if champion.label in existing:
            raise ValueError(
                f"duplicate champion label {champion.label!r} — labels identify "
                f"decks in the payoff matrix and must be unique"
            )
        self.champions.append(champion)

    def __len__(self) -> int:
        return len(self.champions)

    def __iter__(self):
        return iter(self.champions)

    def latest(self, population: str) -> Champion | None:
        found = [c for c in self.champions if c.population == population]
        return found[-1] if found else None

    def of_round(self, round: int) -> list[Champion]:
        return [c for c in self.champions if c.round == round]

    def opponents_for(
        self,
        population: str,
        rng: random.Random,
        *,
        n_recent: int = 4,
        n_historic: int = 2,
    ) -> list[Champion]:
        """Who this population trains against: the current field plus history.

        The current champions of the *other* populations are what makes this a
        metagame; the historic sample is what stops the population from cycling
        back into something an older opponent already beat. Dropping the historic
        half is the single easiest way to get a co-evolution run that looks
        healthy and has learned nothing.
        """
        others = [c for c in self._current().values() if c.population != population]
        recent = others[-n_recent:] if n_recent else []

        pool = [c for c in self.champions if c not in recent]
        historic = rng.sample(pool, min(n_historic, len(pool))) if pool else []

        chosen = recent + historic
        if not chosen and self.champions:
            chosen = [self.champions[-1]]
        return chosen

    def _current(self) -> dict[str, Champion]:
        current: dict[str, Champion] = {}
        for champion in self.champions:
            current[champion.population] = champion
        return current


# --- game theory --------------------------------------------------------


def payoff_matrix(
    arena: Arena,
    champions: Sequence[Champion],
    *,
    n_games: int,
    seed: int,
) -> list[list[float]]:
    """Full round robin. `m[i][j]` is `i`'s win rate against `j`.

    Only the upper triangle is simulated; the lower is filled by symmetry, since
    a win for one side is a loss for the other. That halves the cost and — more
    importantly — guarantees the matrix is exactly antisymmetric about 0.5, which
    the Nash solver relies on.

    Every pairing is collected before any is played, so an arena that implements
    `payoff_all` can run the whole round robin in parallel. By the fourth round
    the archive is twenty decks and the matrix is 190 matches; played one at a
    time it costs more than the searches that produced them.
    """
    n = len(champions)
    matrix = [[0.5] * n for _ in range(n)]

    pairings = [(i, j) for i in range(n) for j in range(i + 1, n)]
    if not pairings:
        return matrix

    jobs = [
        (champions[i], champions[j], n_games, seed + i * 1_000 + j) for i, j in pairings
    ]
    batch = getattr(arena, "payoff_all", None)
    if batch is not None:
        scores = batch(jobs)
    else:
        scores = [arena.payoff(a, b, n_games=g, seed=s) for a, b, g, s in jobs]

    for (i, j), score in zip(pairings, scores):
        matrix[i][j] = score
        matrix[j][i] = 1.0 - score
    return matrix


def nash(matrix: Sequence[Sequence[float]], iterations: int = 20_000) -> list[float]:
    """Nash mixture over decks, by fictitious play.

    A symmetric zero-sum game's equilibrium is generally a *mixture*, not a single
    deck — which is the precise sense in which "the best deck" often does not
    exist. Reporting the mixture instead of an argmax is the difference between
    describing a metagame and mistaking one corner of it for the whole thing.

    Fictitious play rather than replicator dynamics: replicator can orbit forever
    on exactly the intransitive games this module exists to detect, whereas
    fictitious play's time-average is guaranteed to converge for two-player
    zero-sum.
    """
    n = len(matrix)
    if n == 0:
        return []
    if n == 1:
        return [1.0]

    counts = [0.0] * n
    counts[0] = 1.0

    for _ in range(iterations):
        total = sum(counts)
        expected = [
            sum(matrix[i][j] * counts[j] for j in range(n)) / total for i in range(n)
        ]
        best = max(range(n), key=lambda i: expected[i])
        counts[best] += 1.0

    total = sum(counts)
    return [c / total for c in counts]


def cycles(
    matrix: Sequence[Sequence[float]], labels: Sequence[str], *, margin: float = 0.02
) -> list[tuple[str, str, str]]:
    """Intransitive triples: i beats j beats k beats i.

    `margin` keeps coin-flip matchups from being read as edges — without it a
    matrix of 0.50s reports a cycle between every three decks in it.
    """
    n = len(matrix)
    threshold = 0.5 + margin
    found: list[tuple[str, str, str]] = []
    for i in range(n):
        for j in range(n):
            if j == i or matrix[i][j] <= threshold:
                continue
            for k in range(n):
                if k in (i, j) or matrix[j][k] <= threshold:
                    continue
                if matrix[k][i] > threshold:
                    triple = (labels[i], labels[j], labels[k])
                    if not _rotation_seen(triple, found):
                        found.append(triple)
    return found


def _rotation_seen(triple, found) -> bool:
    rotations = {triple, (triple[1], triple[2], triple[0]), (triple[2], triple[0], triple[1])}
    return any(f in rotations for f in found)


def score_against_mixture(
    arena: Arena,
    champion: Champion,
    field: Sequence[Champion],
    mixture: Sequence[float],
    *,
    n_games: int,
    seed: int,
) -> float:
    """Win rate against a weighted field — the comparable-across-rounds number."""
    if not field:
        return 0.5
    total = 0.0
    for weight, opponent in zip(mixture, field):
        if weight <= 1e-6 or opponent.label == champion.label:
            total += weight * 0.5
            continue
        total += weight * arena.payoff(champion, opponent, n_games=n_games, seed=seed)
    return total


# --- the driver ---------------------------------------------------------


@dataclass
class RoundReport:
    round: int
    champions: list[Champion]
    matrix: list[list[float]]
    labels: list[str]
    mixture: list[float]
    intransitive: list[tuple[str, str, str]]
    progress: dict[str, float]
    """Each new champion's win rate against the *previous* round's Nash mixture.

    Above 0.5 means it beat the field as it stood before this round — the only
    honest claim of progress available when the objective is moving.
    """

    def top(self, k: int = 5) -> list[tuple[str, float]]:
        ranked = sorted(zip(self.labels, self.mixture), key=lambda p: -p[1])
        return [(name, w) for name, w in ranked[:k] if w > 1e-3]


@dataclass
class CoevolutionResult:
    archive: Archive
    rounds: list[RoundReport]

    @property
    def final(self) -> RoundReport:
        return self.rounds[-1]


def coevolve(
    arena: Arena,
    populations: Sequence[str],
    optimizer_factory: Callable[[str, int], object],
    runner: Callable[[Problem, object, int], tuple[tuple[int, ...], float]],
    *,
    rounds: int = 4,
    seed: int = 0,
    matrix_games: int = 600,
    progress_games: int = 600,
    n_recent: int = 4,
    n_historic: int = 2,
    on_round: Callable[[RoundReport], None] | None = None,
) -> CoevolutionResult:
    """Run the tournament. Populations improve against each other, round by round.

    `runner` executes one search and returns `(vector, score)`; keeping it a
    parameter means this driver never needs to know about oracles or budgets, and
    the whole loop stays testable against a fake.
    """
    rng = random.Random(seed)
    archive = Archive()
    reports: list[RoundReport] = []
    previous_field: list[Champion] = []
    previous_mixture: list[float] = []

    for round_index in range(1, rounds + 1):
        fresh: list[Champion] = []

        for population in populations:
            opponents = archive.opponents_for(
                population, rng, n_recent=n_recent, n_historic=n_historic
            )
            problem = arena.problem_for(population, opponents)
            optimizer = optimizer_factory(population, round_index)
            vector, score = runner(problem, optimizer, seed + round_index)
            champion = arena.to_champion(population, round_index, vector, score)
            archive.add(champion)
            fresh.append(champion)

        # Progress is measured against the field as it stood *before* this round.
        progress = {
            champion.label: score_against_mixture(
                arena, champion, previous_field, previous_mixture,
                n_games=progress_games, seed=seed + round_index,
            )
            for champion in fresh
        } if previous_field else {}

        field = list(archive)
        labels = [c.label for c in field]
        matrix = payoff_matrix(arena, field, n_games=matrix_games, seed=seed + round_index)
        mixture = nash(matrix)

        report = RoundReport(
            round=round_index,
            champions=fresh,
            matrix=matrix,
            labels=labels,
            mixture=mixture,
            intransitive=cycles(matrix, labels),
            progress=progress,
        )
        reports.append(report)
        if on_round is not None:
            on_round(report)

        previous_field, previous_mixture = field, mixture

    return CoevolutionResult(archive=archive, rounds=reports)
