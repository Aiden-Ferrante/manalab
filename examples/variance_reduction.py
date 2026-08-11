"""Phase 2 gate: how much does common random numbers actually buy?

Measures the realized variance reduction on the real simulator rather than
quoting the textbook. Two decks one swap apart are compared both ways — sharing
a stream, and on independent streams — and the ratio of the resulting standard
errors is the effective budget multiplier for every comparison downstream.

    python examples/variance_reduction.py
"""

from __future__ import annotations

import statistics

from manalab.search.compare import games_needed, paired, unpaired
from manalab.search.oracle import Oracle
from manalab.search.problems import enumerable_tier

GAMES = 20_000
TRIALS = 8


def main() -> None:
    tier = enumerable_tier(24)
    problem = tier.problem

    # Two decks one swap apart, and a pair further apart, to see how the
    # coupling decays with distance.
    base = (10, 6, 4, 4)
    pairs = {
        "1 swap": (base, (11, 5, 4, 4)),
        "2 swaps": (base, (12, 4, 4, 4)),
        "6 swaps": (base, (16, 4, 4, 0)),
    }

    print(f"{GAMES:,} games per deck, {TRIALS} independent trials, "
          f"objective = {problem.objective.name}\n")
    print(f"{'apart':<9}{'rho':>7}{'se paired':>12}{'se unpaired':>13}"
          f"{'budget multiplier':>19}")

    for label, (a, b) in pairs.items():
        rhos, se_p, se_u, ratios = [], [], [], []

        for trial in range(TRIALS):
            oracle = Oracle(problem, budget=GAMES * 4 + 10, seed=trial)

            # Paired: both decks on one stream, game for game.
            oracle.evaluate(a, GAMES, stream=trial)
            oracle.evaluate(b, GAMES, stream=trial)
            p = paired(oracle.samples(a, trial), oracle.samples(b, trial))

            # Unpaired: deliberately different streams.
            oracle.evaluate(a, GAMES, stream=100 + trial)
            oracle.evaluate(b, GAMES, stream=200 + trial)
            u = unpaired(oracle.samples(a, 100 + trial), oracle.samples(b, 200 + trial))

            rhos.append(p.correlation)
            se_p.append(p.stderr)
            se_u.append(u.stderr)
            ratios.append((u.stderr / p.stderr) ** 2 if p.stderr else float("nan"))

        print(
            f"{label:<9}{statistics.fmean(rhos):>7.3f}"
            f"{statistics.fmean(se_p):>12.6f}{statistics.fmean(se_u):>13.6f}"
            f"{statistics.fmean(ratios):>18.1f}x"
        )

    print(
        "\nThe coupling decays with distance: CRN pays most for the 1-swap moves\n"
        "local search makes, and much less for the distant comparisons that\n"
        "population methods rely on. Budget accounting should expect that."
    )

    # What the multiplier means in the only currency that matters.
    print("\nGames needed to detect a 1-point effect at 80% power:")
    oracle = Oracle(problem, budget=GAMES * 2 + 10, seed=99)
    oracle.evaluate(base, GAMES, stream=0)
    oracle.evaluate((11, 5, 4, 4), GAMES, stream=0)
    sa = oracle.samples(base, 0)
    sb = oracle.samples((11, 5, 4, 4), 0)

    sd_diff = statistics.stdev([x - y for x, y in zip(sa, sb)])
    sd_indep = (2 * statistics.variance(sa)) ** 0.5

    for effect in (0.05, 0.01, 0.005):
        n_p = games_needed(effect, sd_diff)
        n_u = games_needed(effect, sd_indep)
        print(f"  effect {effect:<6}  paired {n_p:>10,}   unpaired {n_u:>12,}"
              f"   {n_u / n_p:>6.1f}x cheaper")


if __name__ == "__main__":
    main()
