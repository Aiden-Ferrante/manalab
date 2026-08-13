"""Replicate the five-colour tournament across seeds, with and without sweepers.

One run of a genetic algorithm is one sample from a noisy process. This session
produced a 0.379 -> 0.609 change in the colour spread after sweepers entered the
gauntlet, from a single seed each — and an earlier check showed two seeds on the
same red problem producing a burn deck and a creature deck. That is more than
enough reason to measure the noise floor before believing the effect.

    python examples/replicate_colors.py --seeds 4 --budget 80000

Reports, per condition, each colour's mean win rate across seeds and its
standard deviation. The number that decides the question is whether the change
in *spread* between conditions is larger than the spread's own variation across
seeds. If it is not, the effect is not there.
"""

from __future__ import annotations

import argparse
import os
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

from manalab.cards.model import Decklist
from manalab.cards.store import CardStore
from manalab.evaluate import gauntlet as G
from manalab.evaluate import pool as P
from manalab.evaluate.match import GauntletDeck, MatchEvaluator
from manalab.search.genetic import GeneticSearch
from manalab.search.objective import WIN_RATE
from manalab.search.problem import Problem
from manalab.search.runner import run_optimizer

REPO = Path(__file__).resolve().parent.parent
COLORS = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}


def _verbs(card):
    return {e.verb for e in card.effects}


def _damage(card):
    return max((float(e.get("amount", 0)) for e in card.effects
                if e.verb == "deal_damage" and isinstance(e.get("amount"), int)),
               default=0.0)


def _plain_answers(card) -> float:
    """The removal archetype *without* any sweeper preference."""
    if G._is_sweeper(card):
        return -1.0          # the whole point of this condition: no sweepers
    if "counter_spell" in _verbs(card) or "destroy" in _verbs(card):
        return 3.0
    if "deal_damage" in _verbs(card):
        return _damage(card) - 1.0
    if "draw" in _verbs(card):
        return 1.0
    return -1.0


NO_SWEEPERS = G.ARCHETYPES + (
    G.SPELL_ARCHETYPES[0],                       # burn, unchanged
    G.Archetype("removal", lands=23, spell_slots=14,
                spell_score=_plain_answers,
                score=lambda c: (
                    (c.base_power or 0) + (c.base_toughness or 0)) / max(1.0, c.cmc)),
)

CONDITIONS = {"no sweepers": NO_SWEEPERS, "with sweepers": G.FULL}


def one_run(store, archetypes, seed, args):
    """Evolve all five colours against `archetypes`, then play them off."""
    pools, champions, cards = {}, {}, {}
    for code, name in COLORS.items():
        pool = P.mono_color(store, code, fmt="modern")
        pools[name] = pool
        cards.update(pool.cards)

    for name, pool in pools.items():
        evaluator = MatchEvaluator(gauntlet=G.standard(pool, archetypes), cards=pool.cards)
        problem = Problem(pool=pool.pool, evaluator=evaluator, objective=WIN_RATE,
                          name=f"mono-{name}/60")
        optimizer = GeneticSearch(population=args.population,
                                  games_per_eval=args.games_per_eval,
                                  workers=args.workers)
        trace = run_optimizer(problem, optimizer, budget=args.budget, seed=seed)
        champions[name] = problem.to_decklist(trace.best.vector, name)

    decks = {name: GauntletDeck(name, tuple(
        c for card, n in deck.counts.items() for c in [cards[card]] * n))
        for name, deck in champions.items()}

    overall = {}
    for name in COLORS.values():
        others = tuple(decks[o] for o in COLORS.values() if o != name)
        evaluator = MatchEvaluator(gauntlet=others, cards=cards)
        result = evaluator.evaluate(champions[name], n_games=args.round_robin_games,
                                    seed=770_000 + seed)
        overall[name] = result.metrics["win_rate"]
    return overall


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=4)
    parser.add_argument("--budget", type=int, default=80_000)
    parser.add_argument("--population", type=int, default=48)
    parser.add_argument("--games-per-eval", type=int, default=50)
    parser.add_argument("--round-robin-games", type=int, default=2_000)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    args = parser.parse_args()

    store = CardStore(REPO / "data" / "cards.duckdb")
    results: dict[str, dict[str, list[float]]] = {
        c: defaultdict(list) for c in CONDITIONS}

    started = time.perf_counter()
    for condition, archetypes in CONDITIONS.items():
        for seed in range(args.seeds):
            overall = one_run(store, archetypes, seed, args)
            for name, score in overall.items():
                results[condition][name].append(score)
            spread = max(overall.values()) - min(overall.values())
            print(f"  {condition:<14} seed {seed}: "
                  + "  ".join(f"{n[:5]}={overall[n]:.3f}" for n in COLORS.values())
                  + f"  spread={spread:.3f}", flush=True)

    print(f"\n{'=' * 78}")
    print(f"REPLICATES — {args.seeds} seeds per condition, "
          f"{(time.perf_counter() - started) / 60:.1f} min")
    print("=" * 78)
    print(f"{'colour':<9}" + "".join(f"{c:>21}" for c in CONDITIONS))

    for name in COLORS.values():
        cells = []
        for condition in CONDITIONS:
            xs = results[condition][name]
            sd = statistics.stdev(xs) if len(xs) > 1 else 0.0
            cells.append(f"{statistics.fmean(xs):.3f} +/- {sd:.3f}")
        print(f"{name:<9}" + "".join(f"{c:>21}" for c in cells))

    print()
    spreads = {}
    for condition in CONDITIONS:
        per_seed = [
            max(results[condition][n][i] for n in COLORS.values())
            - min(results[condition][n][i] for n in COLORS.values())
            for i in range(args.seeds)
        ]
        spreads[condition] = per_seed
        sd = statistics.stdev(per_seed) if len(per_seed) > 1 else 0.0
        print(f"  spread  {condition:<14} {statistics.fmean(per_seed):.3f} +/- {sd:.3f}"
              f"   (seeds: {', '.join(f'{s:.3f}' for s in per_seed)})")

    a, b = (spreads[c] for c in CONDITIONS)
    difference = statistics.fmean(b) - statistics.fmean(a)
    noise = max(
        statistics.stdev(a) if len(a) > 1 else 0.0,
        statistics.stdev(b) if len(b) > 1 else 0.0,
    )
    print(f"\n  difference in spread: {difference:+.3f}")
    print(f"  seed-to-seed noise:   {noise:.3f}")
    if abs(difference) > 2 * noise and noise > 0:
        print("\n  The change is larger than twice the seed noise — worth believing.")
    else:
        print("\n  The change is NOT larger than twice the seed noise.")
        print("  The single-run result that motivated this was not evidence of an effect.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
