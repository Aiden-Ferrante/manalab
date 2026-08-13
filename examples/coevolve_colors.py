"""Five colours co-evolving: each round they optimise against each other.

Stage 3 of the deck-search ladder. Stages 1 and 2 (`evolve_all_colors.py`) built
a champion per colour against a fixed gauntlet and played them off once. Here the
gauntlet *is* the other colours, and it moves every round.

    python examples/coevolve_colors.py --rounds 4 --budget 60000

Read the output in this order:

  progress      each new champion vs the *previous* round's Nash mixture. The
                only number comparable across rounds. Above 0.5 is real progress.
  mixture       the Nash equilibrium over every deck ever built. A single deck at
                ~1.0 means the metagame is degenerate; weight spread over several
                means there is a genuine rock-paper-scissors.
  cycles        intransitive triples. Their presence is what makes a metagame a
                metagame rather than a ladder.

A caveat that does not go away by running more rounds: the engine executes no
rules text, so each colour arrives stripped to its creatures. Removal, burn,
counterspells and card draw — the things that would break up a dominant strategy
— are all inert. Expect this to converge harder than real Magic would.
"""

from __future__ import annotations

import argparse
import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from manalab.cards import decklist as DL
from manalab.cards.model import Decklist
from manalab.cards.store import CardStore
from manalab.evaluate import gauntlet as G
from manalab.evaluate import pool as P
from manalab.evaluate.match import GauntletDeck, MatchEvaluator
from manalab.search.coevolve import Champion, RoundReport, coevolve
from manalab.search.genetic import GeneticSearch
from manalab.search.objective import WIN_RATE
from manalab.search.problem import Problem
from manalab.search.runner import run_optimizer

REPO = Path(__file__).resolve().parent.parent
COLORS = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}
CODE_OF = {name: code for code, name in COLORS.items()}


def _play(job):
    """One pairing, in a worker. Module level so it pickles."""
    counts_a, counts_b, cards, n_games, seed = job
    opponent = GauntletDeck("opponent", _resolve(counts_b, cards))
    evaluator = MatchEvaluator(gauntlet=(opponent,), cards=cards)
    return evaluator.evaluate(Decklist(dict(counts_a)), n_games=n_games, seed=seed
                              ).metrics["win_rate"]


def _resolve(counts, cards):
    return tuple(c for name, n in counts.items() for c in [cards[name]] * n)


class ColorArena:
    """The `Arena` the co-evolution driver talks to. All game knowledge lives here."""

    def __init__(self, store, workers: int, budget: int, seed: int):
        self.pools = {name: P.mono_color(store, code, fmt="modern")
                      for code, name in COLORS.items()}
        self.cards = {}
        for pool in self.pools.values():
            self.cards.update(pool.cards)
        self.workers = workers
        self.budget = budget
        self.seed = seed

    # --- Arena protocol ---

    def problem_for(self, population, opponents):
        pool = self.pools[population]
        if opponents:
            field = tuple(GauntletDeck(c.label, _resolve(c.counts, self.cards))
                          for c in opponents)
        else:
            # Round one has no field yet; fall back to the colour's own archetypes.
            field = G.standard(pool)
        evaluator = MatchEvaluator(gauntlet=field, cards=self.cards)
        return Problem(pool=pool.pool, evaluator=evaluator, objective=WIN_RATE,
                       name=f"mono-{population}/60")

    def to_champion(self, population, round, vector, score):
        pool = self.pools[population]
        deck = pool.pool.from_vector(tuple(vector))
        counts = {k: v for k, v in deck.counts.items() if v}
        # Magic's own WUBRG codes, not the first letter of the name. "black" and
        # "blue" both start with B, and a label collision here is not cosmetic:
        # `score_against_mixture` treats a same-label opponent as a mirror and
        # scores it 0.5, so a black deck would silently skip its blue namesake.
        return Champion(label=f"{CODE_OF[population]}{round}", population=population,
                        round=round, counts=counts, vector=tuple(vector), score=score)

    def payoff(self, a, b, *, n_games, seed):
        return _play((a.counts, b.counts, self.cards, n_games, seed))

    def payoff_all(self, jobs):
        payload = [(a.counts, b.counts, self.cards, n, s) for a, b, n, s in jobs]
        if self.workers <= 1 or len(payload) <= 1:
            return [_play(job) for job in payload]
        with ProcessPoolExecutor(max_workers=self.workers) as pool:
            return list(pool.map(_play, payload, chunksize=1))


def report(round_report: RoundReport) -> None:
    r = round_report
    print(f"\n{'=' * 74}\nROUND {r.round}\n{'=' * 74}")

    if r.progress:
        print("  progress vs the previous round's field:")
        for label, score in sorted(r.progress.items(), key=lambda kv: -kv[1]):
            verdict = "improved" if score > 0.55 else (
                "held" if score > 0.45 else "REGRESSED")
            print(f"     {label:<5} {score:.3f}   {verdict}")
    else:
        print("  (no previous field to measure progress against)")

    print(f"\n  Nash mixture over all {len(r.labels)} decks:")
    for label, weight in r.top(6):
        bar = "#" * int(weight * 40)
        print(f"     {label:<5} {weight:.3f}  {bar}")

    if r.intransitive:
        print(f"\n  intransitive triples ({len(r.intransitive)}):")
        for a, b, c in r.intransitive[:6]:
            print(f"     {a} > {b} > {c} > {a}")
    else:
        print("\n  no cycles — the field is a ladder, not a metagame")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=4)
    parser.add_argument("--budget", type=int, default=60_000)
    parser.add_argument("--population", type=int, default=48)
    parser.add_argument("--games-per-eval", type=int, default=50)
    parser.add_argument("--matrix-games", type=int, default=400)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    args = parser.parse_args()

    store = CardStore(REPO / "data" / "cards.duckdb")
    arena = ColorArena(store, args.workers, args.budget, args.seed)

    print(f"co-evolving {len(COLORS)} colours over {args.rounds} rounds")
    print(f"{args.budget:,} games per search, {args.workers} workers\n")
    for name, pool in arena.pools.items():
        print(f"  {name:<7} pool {pool.size:>3}")

    def make_optimizer(population, round_index):
        return GeneticSearch(population=args.population,
                             games_per_eval=args.games_per_eval,
                             workers=args.workers)

    def run(problem, optimizer, seed):
        trace = run_optimizer(problem, optimizer, budget=args.budget, seed=seed)
        return trace.best.vector, trace.best.score

    started = time.perf_counter()
    result = coevolve(
        arena, list(COLORS.values()), make_optimizer, run,
        rounds=args.rounds, seed=args.seed,
        matrix_games=args.matrix_games, progress_games=args.matrix_games,
        on_round=report,
    )
    elapsed = time.perf_counter() - started

    print(f"\n{'=' * 74}\nFINAL\n{'=' * 74}")
    final = result.final
    print(f"{len(result.archive)} decks built in {elapsed / 60:.1f} min\n")

    weights = dict(zip(final.labels, final.mixture))
    written = set()
    for champion in result.archive:
        weight = weights.get(champion.label, 0.0)
        if weight > 0.01 and champion.label not in written:
            written.add(champion.label)
            out = REPO / "decks" / f"coevo-{champion.label.lower()}.txt"
            out.write_text(
                f"// {champion.population}, co-evolution round {champion.round}\n"
                f"// Nash weight in the final metagame: {weight:.3f}\n\n"
                + DL.dumps(Decklist(dict(champion.counts))) + "\n",
                encoding="utf-8")
            print(f"  wrote {out.name}  (weight {weight:.3f})")

    survivors = {c.population for c in result.archive
                 if weights.get(c.label, 0) > 0.01}
    print(f"\ncolours surviving in the equilibrium: {', '.join(sorted(survivors))}")
    if len(survivors) == 1:
        print("A one-colour equilibrium is the degenerate outcome — nothing in this")
        print("engine punishes the dominant strategy, because everything that would")
        print("is an instant that resolves doing nothing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
