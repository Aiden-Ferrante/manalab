"""Phase 1 gate: can an optimizer recover a known optimum?

The analytic tier's optimum comes from a closed-form hypergeometric, computed
without touching the simulator, so regret here is exact — no ground-truth noise
to hide behind.

    python -u examples/phase1_gate.py

Reports mean regret and hit rate. A method that never hits the optimum is not
necessarily broken; the interesting question is whether it stops *because it
converged* or *because it ran out of resolution*, which is what the alpha
variants are here to separate.
"""

from __future__ import annotations

import statistics
from collections import Counter

from manalab.search.baselines import CoordinateSearch, FixedDeck, RandomSearch
from manalab.search.moves import count_decks
from manalab.search.problems import analytic_tier, p_castable_one_drop
from manalab.search.runner import run_optimizer

SEEDS = 12
BUDGETS = (50_000, 200_000)


def true_score(vector: tuple[int, ...]) -> float:
    return p_castable_one_drop(vector[0], vector[1], 40)


def main() -> None:
    tier = analytic_tier(40)
    problem = tier.problem
    n_decks = count_decks(problem.pool.upper_bounds, problem.pool.deck_size)

    print(f"{problem.name}: {n_decks} feasible decks")
    print(f"optimum {tier.optimum} = {tier.optimum_score:.6f}  ({tier.describe})")
    print(f"{SEEDS} seeds per cell, each with its own stream block\n")

    methods = [
        ("random", lambda: RandomSearch(games_per_deck=2_000)),
        ("coord", lambda: CoordinateSearch(games_per_eval=2_000)),
        ("coord+paired", lambda: CoordinateSearch(games_per_eval=2_000, alpha=0.05)),
        ("centre", lambda: FixedDeck((13, 13, 14), label="centre")),
    ]

    print(f"{'method':<14}{'budget':>9}{'spent':>9}{'regret':>10}{'sd':>9}"
          f"{'hits':>7}   most common deck")

    for label, make in methods:
        for budget in BUDGETS:
            regrets, spent, finals = [], [], []
            for seed in range(SEEDS):
                trace = run_optimizer(problem, make(), budget=budget, seed=seed)
                final = tuple(trace.config["final_vector"])
                regrets.append(tier.optimum_score - true_score(final))
                spent.append(trace.games_spent)
                finals.append(final)

            deck, count = Counter(finals).most_common(1)[0]
            hits = sum(f == tier.optimum for f in finals)
            print(
                f"{label:<14}{budget:>9}{int(statistics.fmean(spent)):>9}"
                f"{statistics.fmean(regrets):>10.5f}{statistics.pstdev(regrets):>9.5f}"
                f"{hits:>5}/{SEEDS}   {deck} x{count}"
            )

    print(
        "\nRegret is measured against the exact optimum, so a method that leaves\n"
        "budget unspent is not being penalised for stopping early — it is being\n"
        "penalised for stopping in the wrong place."
    )


if __name__ == "__main__":
    main()
