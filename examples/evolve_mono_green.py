"""Evolve a mono-green deck against the standard gauntlet, and write it out.

The notebook (`notebooks/genetic_deck_search.ipynb`) is the version to read;
this is the version to run when you just want the decklist.

    python examples/evolve_mono_green.py
    python examples/evolve_mono_green.py --budget 400000 --seed 3

Note the `if __name__ == "__main__":` guard at the bottom. It is required, not
stylistic: worker processes re-import this module to find the code they run, so
without it every worker starts its own search.
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from manalab.cards import decklist as DL
from manalab.cards.store import CardStore
from manalab.evaluate import gauntlet as G
from manalab.evaluate import pool as P
from manalab.evaluate.match import MatchEvaluator
from manalab.search.genetic import GeneticSearch
from manalab.search.objective import WIN_RATE
from manalab.search.oracle import Oracle
from manalab.search.problem import Problem
from manalab.search.runner import run_optimizer

REPO = Path(__file__).resolve().parent.parent
AUDIT_STREAM = 999
"""A stream the search never touches, so the final score is not the one it chose on."""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=int, default=150_000, help="simulated games")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--population", type=int, default=48)
    parser.add_argument("--games-per-eval", type=int, default=50)
    parser.add_argument("--audit-games", type=int, default=3_000)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    parser.add_argument("--out", type=Path, default=REPO / "decks" / "mono-green-ga.txt")
    args = parser.parse_args()

    store = CardStore(REPO / "data" / "cards.duckdb")
    pool = P.mono_color(store, "G", fmt="modern")
    gauntlet = G.standard(pool)
    evaluator = MatchEvaluator(gauntlet=gauntlet, cards=pool.cards)
    problem = Problem(pool=pool.pool, evaluator=evaluator, objective=WIN_RATE,
                      name="mono-green/60")

    print(f"pool: {pool.size} faithful cards ({len(pool.text_tier)} set aside)")
    print(f"gauntlet: {', '.join(d.name for d in gauntlet)}")
    print(f"budget: {args.budget:,} games on {args.workers} workers\n")

    optimizer = GeneticSearch(
        population=args.population,
        games_per_eval=args.games_per_eval,
        workers=args.workers,
    )

    started = time.perf_counter()
    trace = run_optimizer(problem, optimizer, budget=args.budget, seed=args.seed)
    elapsed = time.perf_counter() - started

    champion = problem.to_decklist(trace.best.vector, "mono-green-ga")

    # The score the search reports is the maximum of many noisy measurements and
    # is biased upward. Re-measure on games it never saw before writing it down.
    audit = Oracle(problem, budget=args.audit_games * 2, seed=args.seed)
    held = audit.evaluate(trace.best.vector, args.audit_games, stream=AUDIT_STREAM)
    margin = 1.96 * held.stderr

    lands = sum(n for c, n in champion.counts.items() if pool.cards[c].is_land)
    dorks = sum(n for c, n in champion.counts.items()
                if pool.cards[c].taps_for_mana and not pool.cards[c].is_land)

    print(f"{trace.games_spent:,} games in {elapsed:.1f}s "
          f"({elapsed / max(1, trace.games_spent) * 1e6:.0f} us/game)")
    print(f"in-sample {trace.best.score:.3f}  ->  held out {held.score:.3f} "
          f"+/- {margin:.3f}  (winner's curse {trace.best.score - held.score:+.3f})")
    print(f"{lands} lands + {dorks} mana creatures = {lands + dorks} sources\n")

    header = (
        f"// mono-green, evolved\n"
        f"//\n"
        f"// search.genetic over the {pool.size}-card faithful mono-green pool, scored by\n"
        f"// win rate against the gauntlet in evaluate.gauntlet.\n"
        f"// Reproduce: examples/evolve_mono_green.py --budget {args.budget} --seed {args.seed}\n"
        f"//\n"
        f"// Held out over {args.audit_games:,} fresh games: {held.score:.3f} +/- {margin:.3f}.\n"
        f"// Both seats piloted by engine.agents.CurveAgent, so that number means\n"
        f"// 'beats this gauntlet under this pilot' and nothing stronger.\n"
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(header + "\n" + DL.dumps(champion) + "\n", encoding="utf-8")

    for name, count in sorted(champion.counts.items(), key=lambda kv: (-kv[1], kv[0])):
        if not count:
            continue
        card = pool.cards[name]
        body = f"{card.power}/{card.toughness}" if card.is_creature else "land"
        print(f"{count:>2} {name:<26} {str(card.cost):<13} {body:<6} "
              f"{' '.join(sorted(card.keywords))}")

    print(f"\nwrote {args.out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
