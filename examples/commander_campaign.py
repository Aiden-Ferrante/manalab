"""The first Commander deck-search campaign, run with the retraction discipline.

Step 0 measures cost and noise before anything is believed. The GA then searches
the faithful pool against a fixed three-deck gauntlet, replicated across seeds;
champions are re-measured on a HELD-OUT gauntlet and a fresh stream, and the
report prints tiers, never a ranking. The number means: "wins this table under
this pilot." Nothing more is claimed.
"""

from __future__ import annotations

import statistics
import sys
import time

from manalab.cards import formats as F
from manalab.cards.model import Decklist
from manalab.cards.store import CardStore
from manalab.evaluate import pool as P
from manalab.evaluate.commander import (CommanderDeck, CommanderDecklistEvaluator)
from manalab.search.genetic import GeneticSearch
from manalab.search.objective import WIN_RATE
from manalab.search.oracle import Oracle
from manalab.search.problem import Problem
from manalab.search.report import Measurement, table

SEEDS = (1, 2, 3)
GA_BUDGET = 700          # games per seed, sized by step 0's cost measurement
HELD_OUT_GAMES = 64


def build_decks(store, pool):
    cards = pool.cards
    forest = store.by_name("Forest")
    generals = sorted((c for c in cards.values()
                       if "Legendary" in c.type_line and c.is_creature),
                      key=lambda c: c.cmc)
    general = generals[0]
    others = [c for c in cards.values() if c.name != general.name and not c.is_land]

    def deck(name, picker, n_spells=62):
        picked = sorted(others, key=picker)[:n_spells]
        return CommanderDeck(name, general,
                             tuple(picked) + tuple([forest] * (99 - len(picked))))

    aggro = deck("aggro", lambda c: (c.cmc, c.name))
    big = deck("big", lambda c: (-c.cmc, c.name))
    mid = deck("mid", lambda c: (abs(c.cmc - 3), c.name))
    ramp = deck("ramp", lambda c: (0 if "search_library" in {e.verb for e in c.effects}
                                   else 1, c.cmc, c.name))
    return general, (aggro, big, mid), ramp


def main() -> int:
    store = CardStore()
    pool = P.mono_color(store, "G", fmt=F.COMMANDER, max_cmc=99)
    general, gauntlet, held_out_deck = build_decks(store, pool)
    print(f"pool {pool.size} faithful; general: {general.name}", flush=True)

    names = tuple(n for n in pool.pool.card_ids if n != general.name)
    legal = F.COMMANDER.legal_names(store)
    search_pool = F.COMMANDER.candidate_pool(names, legal)
    from dataclasses import replace as dc_replace
    search_pool = dc_replace(search_pool, deck_size=99)

    evaluator = CommanderDecklistEvaluator(general.name, pool.cards, gauntlet)

    # --- step 0: cost and noise floor, before anything is believed ---------
    t0 = time.time()
    probe = evaluator.evaluate(Decklist({"Forest": 40, **{n: 1 for n in names[:59]}},
                                        "probe"), n_games=8, seed=900)
    per_game = (time.time() - t0) / 8
    floors = [evaluator.evaluate(Decklist({"Forest": 40, **{n: 1 for n in names[:59]}},
                                          "probe"), n_games=8, seed=s).metrics["win_rate"]
              for s in (901, 909, 917)]
    noise = statistics.pstdev(floors)
    print(f"step 0: {per_game:.1f}s/game; probe win {probe.metrics['win_rate']:.2f}; "
          f"noise floor (8-game seeds) ±{noise:.3f}", flush=True)

    # --- the search, replicated -------------------------------------------
    champions = []
    for seed in SEEDS:
        problem = Problem(pool=search_pool, evaluator=evaluator,
                          objective=WIN_RATE, name=f"cmd-{seed}")
        oracle = Oracle(problem, budget=GA_BUDGET, seed=seed)
        GeneticSearch(population=8, games_per_eval=4, games_cap=64, elite=2).run(oracle)
        best = oracle.trace.best
        champions.append((seed, best))
        print(f"seed {seed}: in-sample best {best.score:.2f} "
              f"({oracle.trace.games_spent} games)", flush=True)

    # --- held out: fresh gauntlet, fresh stream ----------------------------
    held = CommanderDecklistEvaluator(general.name, pool.cards,
                                      (held_out_deck, gauntlet[0], gauntlet[1]))
    measurements = []
    for seed, best in champions:
        deck = search_pool.from_vector(best.vector, f"champion-s{seed}")
        result = held.evaluate(deck, n_games=HELD_OUT_GAMES, seed=7000 + seed)
        measurements.append(Measurement(f"champion-s{seed}",
                                        list(result.samples["win_rate"])))
        print(f"champion-s{seed}: held-out {result.metrics['win_rate']:.2f} "
              f"(in-sample was {best.score:.2f})", flush=True)

    baseline = held.evaluate(
        Decklist({"Forest": 37, **{n: 1 for n in names[:62]}}, "baseline"),
        n_games=HELD_OUT_GAMES, seed=7100)
    measurements.append(Measurement("hand baseline",
                                    list(baseline.samples["win_rate"])))

    print("\n" + table(measurements), flush=True)
    winner = max(champions, key=lambda c: c[1].score)
    deck = search_pool.from_vector(winner[1].vector, "champion")
    top = sorted(deck.counts.items(), key=lambda kv: -kv[1])[:12]
    print(f"\nchampion-s{winner[0]} composition (top slots): {top}", flush=True)
    lands = deck.counts.get("Forest", 0)
    print(f"lands: {lands}/99", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
