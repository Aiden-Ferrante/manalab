"""Benchmark problems with known answers.

You cannot rank optimizers without problems whose optimum you already know, and
the two ways of knowing are closed form and exhaustion. Both are here.

  analytic_tier()    3-card pool, objective with an exact hypergeometric optimum
  enumerable_tier()  small pool, every feasible deck brute-forced by simulation
  realistic_tier()   full pool, no known optimum — rank by held-out score

The analytic tier does double duty: because the closed form is computed without
touching the simulator, comparing it to the simulated value validates the
*simulator* at the same time as it grades the optimizer. If those two disagree,
fix that before believing anything downstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import comb
from typing import Iterator, Mapping, Sequence

from manalab.cards.mana import parse_cost
from manalab.cards.model import CandidatePool, Card
from manalab.evaluate.consistency import ConsistencyEvaluator
from manalab.search.objective import LinearObjective
from manalab.search.problem import Problem

Vector = tuple[int, ...]

OPENING_HAND = 7


def always_keep(hand, mulligans) -> bool:  # noqa: ANN001 - matches KeepPolicy
    """Never mulligan.

    The analytic tier needs this: a London mulligan makes the opening hand a
    *selected* sample, and the closed forms below assume a plain uncontrolled
    draw. Any tier compared against a hypergeometric must disable mulligans, or
    the sim will legitimately disagree with the maths.
    """
    return True


# --- closed forms --------------------------------------------------------


def p_at_least(successes: int, population: int, draws: int, k: int) -> float:
    """P(at least `k` of `successes` appear in `draws` from `population`)."""
    if k <= 0:
        return 1.0
    total = comb(population, draws)
    if total == 0:
        return 0.0
    hits = sum(
        comb(successes, i) * comb(population - successes, draws - i)
        for i in range(k, min(draws, successes) + 1)
        if draws - i <= population - successes
    )
    return hits / total


def p_castable_one_drop(lands: int, spells: int, deck_size: int, hand: int = OPENING_HAND) -> float:
    """P(opening hand contains at least one land *and* at least one one-drop).

    Trivariate hypergeometric over (lands, spells, everything else). This is the
    analytic tier's objective, and it has a genuine interior optimum: too few
    lands and you cannot cast, too many and you have nothing to cast.
    """
    other = deck_size - lands - spells
    if other < 0:
        raise ValueError("lands + spells exceeds deck size")
    total = comb(deck_size, hand)
    if total == 0:
        return 0.0

    hits = 0
    for n_land in range(1, min(hand, lands) + 1):
        for n_spell in range(1, min(hand - n_land, spells) + 1):
            rest = hand - n_land - n_spell
            if 0 <= rest <= other:
                hits += comb(lands, n_land) * comb(spells, n_spell) * comb(other, rest)
    return hits / total


# --- tiers ---------------------------------------------------------------

_MOUNTAIN = Card("Mountain", "Mountain", parse_cost(None), "Land",
                 produces=frozenset("R"), taps_for_mana=True)
_BOLT = Card("Bolt", "Bolt", parse_cost("{R}"), "Instant")
_FILLER = Card("Filler", "Filler", parse_cost("{7}"), "Sorcery")
"""Deliberately uncastable within the simulated turns: it is dead weight whose
only job is to make the land/spell trade-off nontrivial."""

_TIER_CARDS = {c.name: c for c in (_MOUNTAIN, _BOLT, _FILLER)}


@dataclass(frozen=True)
class Tier:
    problem: Problem
    optimum: Vector | None
    """Known best deck, when there is one."""
    optimum_score: float | None
    describe: str = ""

    def regret(self, vector: Vector, score: float) -> float:
        """How far below the known optimum a result landed."""
        if self.optimum_score is None:
            raise ValueError(f"{self.problem.name} has no known optimum")
        return self.optimum_score - score


def analytic_tier(deck_size: int = 40) -> Tier:
    """Maximise P(turn-one Bolt) over (Mountain, Bolt, Filler).

    Optimum found by evaluating the closed form on every feasible deck, so it is
    exact — no simulation, no noise, no sampling error.
    """
    pool = CandidatePool(
        card_ids=("Mountain", "Bolt", "Filler"),
        max_copies={"Mountain": deck_size, "Bolt": deck_size, "Filler": deck_size},
        deck_size=deck_size,
    )

    best, best_score = None, -1.0
    for lands in range(deck_size + 1):
        for spells in range(deck_size - lands + 1):
            score = p_castable_one_drop(lands, spells, deck_size)
            if score > best_score:
                best, best_score = (lands, spells, deck_size - lands - spells), score

    problem = Problem(
        pool=pool,
        evaluator=ConsistencyEvaluator(
            cards=_TIER_CARDS,
            turns=1,
            curve_turns=(),
            targets=(("Bolt", 1),),
            keep=always_keep,
        ),
        objective=LinearObjective({"castable_bolt_by_t1": 1.0}, name="bolt_t1"),
        name=f"analytic{deck_size}",
    )
    return Tier(
        problem=problem,
        optimum=best,
        optimum_score=best_score,
        describe="P(>=1 land and >=1 Bolt in opener), exact by hypergeometric",
    )


def enumerable_tier(deck_size: int = 24) -> Tier:
    """Small enough to brute-force every feasible deck.

    Ground truth here is the *actual* simulated objective rather than a closed
    form, so it grades optimizers on the real problem — mulligans, sequencing
    and all — at the cost of needing `brute_force()` run once.
    """
    cards = dict(_TIER_CARDS)
    cards["Bear"] = Card("Bear", "Bear", parse_cost("{1}{R}"), "Creature — Bear")

    pool = CandidatePool(
        card_ids=("Mountain", "Bolt", "Bear", "Filler"),
        max_copies={"Mountain": deck_size, "Bolt": 8, "Bear": 8, "Filler": 8},
        deck_size=deck_size,
    )
    problem = Problem(
        pool=pool,
        evaluator=ConsistencyEvaluator(
            cards=cards, turns=4, curve_turns=(2, 3), targets=(("Bear", 2),)
        ),
        objective=LinearObjective(
            {"castable_bear_by_t2": 1.0, "p_on_curve_t3": 1.0}, name="bear2+curve3"
        ),
        name=f"enumerable{deck_size}",
    )
    return Tier(problem=problem, optimum=None, optimum_score=None,
                describe="brute-forceable; call brute_force() to fill in the optimum")


def enumerate_feasible(pool: CandidatePool) -> Iterator[Vector]:
    """Every legal deck. Grows combinatorially — check `count_feasible` first."""
    bounds = pool.upper_bounds
    n = len(bounds)

    def walk(idx: int, left: int, acc: tuple[int, ...]) -> Iterator[Vector]:
        if idx == n - 1:
            if left <= bounds[idx]:
                yield acc + (left,)
            return
        for take in range(min(bounds[idx], left) + 1):
            yield from walk(idx + 1, left - take, acc + (take,))

    yield from walk(0, pool.deck_size, ())


def count_feasible(pool: CandidatePool) -> int:
    return sum(1 for _ in enumerate_feasible(pool))


def brute_force(
    problem: Problem, games_per_deck: int = 20_000, stream: int = 0
) -> list[tuple[Vector, float]]:
    """Score every feasible deck. Returns them ranked, best first.

    Expensive on purpose: this is ground truth, so it is measured far more
    precisely than anything under test. Uses one shared stream, so the ranking
    is internally paired and the ordering is much better resolved than the
    individual standard errors suggest.
    """
    from manalab.search.oracle import Oracle

    decks = list(enumerate_feasible(problem.pool))
    oracle = Oracle(problem, budget=games_per_deck * len(decks) + 1, seed=0)

    scored = [
        (deck, oracle.evaluate(deck, games_per_deck, stream=stream, tag="truth").score)
        for deck in decks
    ]
    scored.sort(key=lambda pair: -pair[1])
    return scored
