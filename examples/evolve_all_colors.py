"""Evolve a deck for each mono colour, replicated across seeds.

**Replicated by default, and that is the point.** A genetic algorithm is a
stochastic process; one run is one sample. This script used to run each colour
once and print a ranking, which is how a whole session of engine work came to be
narrated through differences (≤0.13) smaller than the seed-to-seed noise (±0.12).

So: every colour is evolved at several seeds, results are reported as mean plus
spread, and the ranking is printed as *tiers* — colours whose difference is
inside the noise appear together rather than in an order. `--seeds 1` is
available and prints its own warning, because sometimes you just want a deck.

    python examples/evolve_all_colors.py                 # 4 seeds, replicated
    python examples/evolve_all_colors.py --seeds 8       # tighter error bars
    python examples/evolve_all_colors.py --seeds 1       # one run, no claims

Two things happen here, and only the first is a fair experiment:

1. Each colour is optimised against *its own* gauntlet, built from its own pool.
   That is well-posed per colour: what is the best deck buildable from the cards
   of this colour that the engine models exactly?

2. The champions then play a round robin. The engine does not execute every
   card, so each colour arrives partly stripped; the cross-colour table measures
   the engine's blind spots as much as it measures Magic.
"""

from __future__ import annotations

import argparse
import os
import statistics
import time
from collections import defaultdict
from pathlib import Path

from manalab.cards import decklist as DL
from manalab.cards.model import Decklist
from manalab.cards.store import CardStore
from manalab.evaluate import gauntlet as G
from manalab.evaluate import pool as P
from manalab.evaluate.match import GauntletDeck, MatchEvaluator
from manalab.search import report
from manalab.search.genetic import GeneticSearch
from manalab.search.objective import WIN_RATE
from manalab.search.oracle import Oracle
from manalab.search.problem import Problem
from manalab.search.runner import run_optimizer

REPO = Path(__file__).resolve().parent.parent
COLORS = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}
AUDIT_STREAM = 999


def evolve(pool, seed, args):
    """One colour, one seed. Returns (decklist, held-out score)."""
    evaluator = MatchEvaluator(gauntlet=G.standard(pool), cards=pool.cards)
    problem = Problem(pool=pool.pool, evaluator=evaluator, objective=WIN_RATE,
                      name="mono/60")
    optimizer = GeneticSearch(population=args.population,
                              games_per_eval=args.games_per_eval,
                              workers=args.workers)
    trace = run_optimizer(problem, optimizer, budget=args.budget, seed=seed)

    audit = Oracle(problem, budget=args.audit_games * 2, seed=seed)
    held = audit.evaluate(trace.best.vector, args.audit_games, stream=AUDIT_STREAM)
    return problem.to_decklist(trace.best.vector), held.score


def round_robin(champions, cards, seed, games):
    """Each champion against all the others. Returns {colour: win rate}."""
    decks = {name: GauntletDeck(name, tuple(
        c for card, n in deck.counts.items() for c in [cards[card]] * n))
        for name, deck in champions.items()}

    overall = {}
    for name in champions:
        others = tuple(decks[o] for o in champions if o != name)
        evaluator = MatchEvaluator(gauntlet=others, cards=cards)
        result = evaluator.evaluate(champions[name], n_games=games, seed=770_000 + seed)
        overall[name] = result.metrics["win_rate"]
    return overall


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=4,
                        help="independent runs per colour (default 4)")
    parser.add_argument("--budget", type=int, default=100_000)
    parser.add_argument("--population", type=int, default=48)
    parser.add_argument("--games-per-eval", type=int, default=50)
    parser.add_argument("--audit-games", type=int, default=2_000)
    parser.add_argument("--round-robin-games", type=int, default=2_000)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    args = parser.parse_args()

    if args.seeds < 2:
        print("WARNING: --seeds 1 produces a number with no error bar.")
        print("         Seed-to-seed noise on this problem is around +/-0.12,")
        print("         which is wider than most differences worth reporting.\n")

    store = CardStore(REPO / "data" / "cards.duckdb")
    pools = {name: P.mono_color(store, code, fmt="modern")
             for code, name in COLORS.items()}
    cards: dict = {}
    for pool in pools.values():
        cards.update(pool.cards)

    print(f"{args.seeds} seeds x {len(COLORS)} colours, "
          f"{args.budget:,} games per search, {args.workers} workers")
    for name, pool in pools.items():
        print(f"  {name:<7} pool {pool.size:>3}")
    print()

    own: dict[str, list[float]] = defaultdict(list)
    versus: dict[str, list[float]] = defaultdict(list)
    decks_by_seed: dict[str, list[Decklist]] = defaultdict(list)

    started = time.perf_counter()
    for seed in range(args.seeds):
        champions = {}
        for name, pool in pools.items():
            deck, held = evolve(pool, seed, args)
            champions[name] = deck
            decks_by_seed[name].append(deck)
            own[name].append(held)

        overall = round_robin(champions, cards, seed, args.round_robin_games)
        for name, score in overall.items():
            versus[name].append(score)
        print(f"  seed {seed}: "
              + "  ".join(f"{n[:5]}={overall[n]:.3f}" for n in COLORS.values()),
              flush=True)

    elapsed = time.perf_counter() - started

    print(f"\n{'=' * 60}")
    print(f"VS OWN GAUNTLET — held out, {args.seeds} seeds")
    print("=" * 60)
    print(report.table(report.summarise(own)))

    print(f"\n{'=' * 60}")
    print(f"CROSS-COLOUR — champions against each other, {args.seeds} seeds")
    print("=" * 60)
    print(report.table(report.summarise(versus)))

    # Write the *representative* deck per colour: the seed closest to the mean.
    # Writing the best seed's deck is the winner's curse in file form — it is the
    # run that got lucky, and it will not reproduce.
    print(f"\n{'=' * 60}")
    print("DECKS  (the seed nearest each colour's mean, not the best)")
    print("=" * 60)
    for name in COLORS.values():
        scores = versus[name]
        mean = statistics.fmean(scores)
        index = min(range(len(scores)), key=lambda i: abs(scores[i] - mean))
        deck = decks_by_seed[name][index]
        out = REPO / "decks" / f"mono-{name}-ga.txt"
        out.write_text(
            f"// mono-{name}, evolved\n"
            f"//\n"
            f"// Representative of {args.seeds} independent runs: this is the seed\n"
            f"// closest to the mean ({scores[index]:.3f} vs mean {mean:.3f}), not the\n"
            f"// best one. Cross-colour win rate across seeds: "
            f"{mean:.3f} +/- {statistics.stdev(scores) if len(scores) > 1 else 0.0:.3f}.\n"
            f"//\n"
            f"// Both seats piloted by engine.agents.CurveAgent.\n\n"
            + DL.dumps(deck) + "\n", encoding="utf-8")
        print(f"  {name:<7} seed {index} ({scores[index]:.3f})  -> {out.name}")

    print(f"\ntotal {elapsed / 60:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
