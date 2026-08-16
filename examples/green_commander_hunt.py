"""Hunt for a mono-green Commander deck: curve economics, GA, real precons.

Three stages, each on the engine suited to it:

1. **Curve economics** (internal engine): land counts are raced under CRN, and
   the winner seeds the GA's starting deck — initialisation beats operator
   tuning at small budgets, measured long ago in this repo.
2. **Search** (internal engine): the halving GA over the faithful pool,
   replicated across seeds. Fast, spliceable, honest within its 381-card scope.
3. **Judgment** (Forge): champions play full-rules games against three
   RANDOMLY DRAWN official precons. Every card real, no fidelity caveat. The
   number means "wins this table under Forge's pilot" — and the champions were
   bred against the internal pilot, so transfer is exactly what is being tested.
"""

from __future__ import annotations

import random
import statistics
import sys
import time
from dataclasses import replace as dc_replace

from manalab.cards import formats as F
from manalab.cards import precons
from manalab.cards.model import Decklist
from manalab.cards.store import CardStore
from manalab.evaluate import pool as P
from manalab.evaluate.commander import CommanderDeck, CommanderDecklistEvaluator
from manalab.evaluate.forge_sim import ForgeSimEvaluator, available
from manalab.search.genetic import GeneticSearch
from manalab.search.objective import WIN_RATE
from manalab.search.oracle import Oracle
from manalab.search.problem import Problem
from manalab.search.report import Measurement, table

SEEDS = (1, 2, 3)
GA_BUDGET = 700
LAND_RACE_GAMES = 48
FORGE_GAMES = 12
PRECON_DRAW_SEED = 20260816


def curve_start(names, cards, lands: int) -> dict[str, int]:
    """A curve-economics starting deck: cheap ramp early, threats on a hump.

    Buckets follow the hypergeometric logic the repo's manafit work fixed:
    heavy at 2-3 mana where green ramps, tapering into a top end.
    """
    spells = [cards[n] for n in names if not cards[n].is_land]
    by_cmc = sorted(spells, key=lambda c: (c.cmc, c.name))
    quota = {1: 8, 2: 14, 3: 13, 4: 10, 5: 7, 6: 4, 7: 3}
    counts: dict[str, int] = {"Forest": lands}
    total = lands
    for card in by_cmc:
        want = quota.get(min(int(card.cmc), 7), 0)
        if want > 0 and total < 99:
            counts[card.name] = 1
            quota[min(int(card.cmc), 7)] = want - 1
            total += 1
    for card in by_cmc:                      # fill any shortfall
        if total >= 99:
            break
        if card.name not in counts:
            counts[card.name] = 1
            total += 1
    return counts


def main() -> int:
    store = CardStore()
    pool = P.mono_color(store, "G", fmt=F.COMMANDER, max_cmc=99)
    generals = sorted((c for c in pool.cards.values()
                       if "Legendary" in c.type_line and c.is_creature),
                      key=lambda c: c.cmc)
    general = generals[0]
    names = tuple(n for n in pool.pool.card_ids if n != general.name)
    print(f"pool {pool.size} faithful; general {general.name}", flush=True)

    gauntlet_deck = CommanderDeck(
        "gauntlet", general,
        tuple(pool.cards[n] for n, c in curve_start(names, pool.cards, 38).items()
              if n != "Forest" for _ in range(c))
        + tuple([store.by_name("Forest")] * 38))
    evaluator = CommanderDecklistEvaluator(
        general.name, pool.cards, [gauntlet_deck] * 3)

    # --- stage 1: race the land counts (curve economics, part one) ---------
    land_results = []
    for lands in (34, 36, 38, 40, 42):
        deck = Decklist(curve_start(names, pool.cards, lands), f"lands{lands}")
        res = evaluator.evaluate(deck, n_games=LAND_RACE_GAMES, seed=500)
        land_results.append((lands, res.metrics["win_rate"], res.stderr("win_rate")))
        print(f"  lands {lands}: {res.metrics['win_rate']:.2f} "
              f"±{res.stderr('win_rate'):.2f}", flush=True)
    best_lands = max(land_results, key=lambda r: r[1])[0]
    print(f"stage 1: {best_lands} lands wins the race", flush=True)

    # --- stage 2: the halving GA, seeded with the curve deck ----------------
    search_pool = dc_replace(F.COMMANDER.candidate_pool(names,
                                                        F.COMMANDER.legal_names(store)),
                             deck_size=99)
    start_deck = Decklist(curve_start(names, pool.cards, best_lands), "curve-start")
    start_vector = search_pool.to_vector(start_deck)
    champions = []
    for seed in SEEDS:
        problem = Problem(pool=search_pool, evaluator=evaluator,
                          objective=WIN_RATE, start=start_vector,
                          name=f"hunt-{seed}")
        oracle = Oracle(problem, budget=GA_BUDGET, seed=seed)
        GeneticSearch(population=8, games_per_eval=4, games_cap=64,
                      elite=2, seed_fraction=0.25).run(oracle)
        best = oracle.trace.best
        champions.append((seed, best))
        print(f"seed {seed}: in-sample {best.score:.2f}", flush=True)

    # --- stage 3: full rules against randomly drawn precons ----------------
    if not available():
        print("Forge unavailable; stopping before judgment", flush=True)
        return 1
    rng = random.Random(PRECON_DRAW_SEED)
    candidates_list = [d for d in precons.commander_precons()
                       if "Collector" not in d["name"]]
    rng.shuffle(candidates_list)
    opponents = []
    for d in candidates_list:
        if len(opponents) == 3:
            break
        try:
            commander, counts = precons.as_decklist(precons.fetch_deck(d["fileName"]))
        except Exception as exc:      # noqa: BLE001 - the draw moves on
            print(f"  skipping {d['name']}: {exc}", flush=True)
            continue
        opponents.append((d["name"].replace(" ", "")[:12], commander, counts))
        print(f"drawn precon: {d['name']} ({commander})", flush=True)
    if len(opponents) < 3:
        print("could not assemble three precons; network down", flush=True)
        return 1

    # A stuck game burns its whole draw-clock; serially the stalls queue.
    # Fanned out, the batch costs max(chunk), and the tightened clock makes a
    # seven-minute game a draw rather than a hostage. Measured: the serial
    # form spent 2934s on one 10-game batch.
    forge = ForgeSimEvaluator(opponents, workers=12, clock_seconds=420)
    measurements = []
    for seed, best in champions:
        deck = search_pool.from_vector(best.vector, f"champ{seed}")
        t0 = time.time()
        res = forge.evaluate(f"champ{seed}", general.name, dict(deck.counts),
                             n_games=FORGE_GAMES, seed=9000 + seed)
        measurements.append(Measurement(f"champion-s{seed}",
                                        list(res.samples["win_rate"])))
        print(f"champion-s{seed}: FULL-RULES {res.metrics['win_rate']:.2f} "
              f"({time.time() - t0:.0f}s)", flush=True)

    base = forge.evaluate("curve-start", general.name,
                          dict(start_deck.counts),
                          n_games=FORGE_GAMES, seed=9100)
    measurements.append(Measurement("curve baseline",
                                    list(base.samples["win_rate"])))

    print("\n" + table(measurements), flush=True)
    winner = max(champions, key=lambda c: c[1].score)
    deck = search_pool.from_vector(winner[1].vector, "champion")
    print(f"\nchampion-s{winner[0]}: {deck.counts.get('Forest', 0)} lands; "
          f"nonland slots: {sum(v for k, v in deck.counts.items() if k != 'Forest')}",
          flush=True)
    top = [k for k, v in sorted(deck.counts.items(), key=lambda kv: -kv[1])
           if k != "Forest"][:15]
    print(f"notable: {top}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
