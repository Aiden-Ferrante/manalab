"""Budget-metered, trace-recording, CRN-aware access to the evaluator.

Optimizers never touch an `Evaluator` directly. They get an `Oracle`, which:

  - meters every simulated game and refuses to overspend
  - records every measurement into the `Trace`
  - defaults every deck onto the *same* random stream, so any two decks are
    paired by common random numbers unless you deliberately opt out
  - accumulates samples incrementally, so asking for more games on a deck you
    already measured simulates only the difference

The last point is what makes racing and successive halving affordable: those
procedures work by repeatedly buying more precision on survivors, and a cache
that could only answer "same n or start over" would throw away most of the
budget.

The incremental trick relies on a property of the evaluator: game *i* of a run
started at seed *s* uses seed *s+i*. So a follow-up call at `seed = s + k` for
`n` games yields games *k..k+n-1* of the very same stream. `ConsistencyEvaluator`
guarantees this; any future evaluator must too.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field
from typing import Mapping

from manalab.search.budget import BudgetExceeded, BudgetMeter
from manalab.search.problem import Problem
from manalab.search.trace import Estimate, Trace

DEFAULT_CRN_SEED = 1_000_003
"""Base of stream 0. Every deck is measured against the same shuffles by default,
which is the pairing that makes small differences detectable. It also means
results are tuned to this stream — hence held-out streams in Phase 6."""

STREAM_STRIDE = 1 << 32
"""Seed distance between consecutive streams.

Streams are *indices*, not seeds. Game *i* of stream *s* uses evaluator seed
`crn_seed + s*STRIDE + i`, so distinct streams can never share a game. Using the
index directly as a seed offset — the obvious implementation — makes stream 1
and stream 2 share every game but one, which silently turns an "independent"
comparison into a paired one and understates its variance by orders of
magnitude. Do not shrink this below the largest games-per-deck you will ever run.
"""

MAX_STREAMS = 4096
"""Streams available to one run, before it would collide with the next run's block."""


def crn_base_for_run(seed: int, base: int = DEFAULT_CRN_SEED) -> int:
    """Start of the stream block belonging to run `seed`.

    Each run gets its own disjoint family of streams. Without this every run
    shares stream 0, so repeating an experiment across seeds re-randomises the
    optimizer's internal choices but replays *the same games* — the measurement
    noise never varies, every run gets stuck in the same place for the same
    reason, and the benchmark reports a variance far below the truth.

    Runs at the same seed still share games across optimizers, which is what
    keeps optimizer-vs-optimizer comparisons paired.
    """
    return base + seed * MAX_STREAMS * STREAM_STRIDE


@dataclass
class _Accumulator:
    """Per-game objective values collected so far for one (deck, stream)."""

    samples: list[float] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.samples)


class Oracle:
    def __init__(
        self,
        problem: Problem,
        budget: int,
        seed: int,
        *,
        crn_seed: int | None = None,
        trace: Trace | None = None,
    ) -> None:
        self.problem = problem
        self.meter = BudgetMeter(budget)
        self.seed = seed
        self.crn_seed = DEFAULT_CRN_SEED if crn_seed is None else crn_seed
        self.rng = random.Random(seed)
        """Randomness for the *optimizer* — kept separate from evaluation streams
        so that changing an optimizer's internal choices cannot silently change
        which games get simulated."""

        self.trace = trace or Trace(
            problem=problem.name, optimizer="", seed=seed, budget=budget
        )
        self._cache: dict[tuple[tuple[int, ...], int], _Accumulator] = {}
        self.unmodeled: dict[str, tuple[str, ...]] = {}

    # --- budget ---------------------------------------------------------

    @property
    def remaining(self) -> int:
        return self.meter.remaining

    @property
    def spent(self) -> int:
        return self.meter.spent

    @property
    def exhausted(self) -> bool:
        return self.meter.exhausted

    # --- measurement ----------------------------------------------------

    def _base(self, stream: int) -> int:
        return self.crn_seed + stream * STREAM_STRIDE

    def evaluate(
        self,
        vector: tuple[int, ...],
        n_games: int,
        *,
        stream: int = 0,
        tag: str = "",
    ) -> Estimate:
        """Measure `vector` to a precision of `n_games` games on `stream`.

        `stream` is an index, not a seed. Stream 0 is the shared CRN stream that
        pairs every deck; any other index is an independent replicate, which is
        how Phase 6 gets held-out measurements.

        `n_games` is a *total*, not an increment: asking for 200 after 50 buys
        150 more games. Raises `BudgetExceeded` if it cannot be afforded — call
        `afford()` first if you would rather shrink the request.
        """
        vector = tuple(vector)
        if not self.problem.is_feasible(vector):
            raise ValueError(f"infeasible deck: sum={sum(vector)}")
        if n_games <= 0:
            raise ValueError("n_games must be positive")
        if n_games > STREAM_STRIDE:
            raise ValueError(
                f"{n_games} games would run past the end of stream {stream} "
                f"and collide with the next one"
            )
        if not 0 <= stream < MAX_STREAMS:
            raise ValueError(
                f"stream {stream} outside this run's block of {MAX_STREAMS}"
            )

        key = (vector, stream)
        acc = self._cache.setdefault(key, _Accumulator())

        need = n_games - len(acc)
        if need > 0:
            if need > self.meter.remaining:
                raise BudgetExceeded(
                    f"need {need} more games for precision {n_games}, "
                    f"{self.meter.remaining} remaining"
                )
            self._simulate(vector, self._base(stream), len(acc), need, acc)
            self.meter.spend(need)

        estimate = self._estimate(vector, stream, acc.samples[:n_games])
        self.trace.record(estimate, self.meter.spent, tag)
        return estimate

    def afford(self, n_games: int, vector: tuple[int, ...], stream: int = 0) -> int:
        """Largest total precision reachable for this deck within budget."""
        have = len(self._cache.get((tuple(vector), stream), _Accumulator()))
        return have + self.meter.clamp(max(0, n_games - have))

    def measured(self, vector: tuple[int, ...], stream: int = 0) -> int:
        """Games already banked for this deck on this stream. Costs nothing."""
        return len(self._cache.get((tuple(vector), stream), _Accumulator()))

    # --- internals ------------------------------------------------------

    def _simulate(
        self,
        vector: tuple[int, ...],
        base: int,
        offset: int,
        count: int,
        acc: _Accumulator,
    ) -> None:
        deck = self.problem.to_decklist(vector)
        result = self.problem.evaluator.evaluate(
            deck, n_games=count, seed=base + offset
        )
        acc.samples.extend(self.problem.objective.samples(result))

        # Blind spots are a property of the deck, not of one measurement. Collect
        # them so a report can never quietly omit that the model didn't fit.
        for card, reasons in result.unmodeled.items():
            self.unmodeled.setdefault(card, tuple(reasons))

    def _estimate(
        self, vector: tuple[int, ...], stream: int, samples: list[float]
    ) -> Estimate:
        n = len(samples)
        mean = statistics.fmean(samples)
        stderr = statistics.stdev(samples) / (n**0.5) if n > 1 else 0.0
        return Estimate(vector=vector, score=mean, stderr=stderr, games=n, stream=stream)

    def samples(self, vector: tuple[int, ...], stream: int = 0) -> tuple[float, ...]:
        """Per-game objective values banked for this deck. Costs nothing.

        Paired tests need the raw per-game vectors, not the summaries — with CRN
        the difference of two decks' samples has far lower variance than the
        difference of their means suggests.
        """
        acc = self._cache.get((tuple(vector), stream))
        return tuple(acc.samples) if acc else ()

    # --- convenience ----------------------------------------------------

    @property
    def pool(self):
        return self.problem.pool

    @property
    def dimension(self) -> int:
        return self.problem.dimension

    def best(self) -> Estimate | None:
        return self.trace.best

    def __repr__(self) -> str:
        return (
            f"Oracle({self.problem.name}, spent={self.spent}/{self.meter.total}, "
            f"decks={len(self._cache)})"
        )
