"""Curve -> hypergraph synergy -> Forge: the three-filter pipeline.

The division of labour the transfer result forced: stages A and B optimise
DETERMINISTIC objectives — a million GA evaluations cannot chase noise because
there is none — and Forge is the only win-rate authority, judging the few
survivors at paired seeds. The internal engine appears nowhere: it is a
filter for other campaigns, never an objective, and here not even that.

Stage A: the curve template (lands + cmc quotas) constrains every candidate.
Stage B: a GA over the FULL green corpus maximises the synergy hypergraph
         score under those quotas — four package emphases (tokens, counters,
         landfall, stompy) seed diverse starting points, plus a staples core.
Stage C: champions face three real precons at the SAME seed schedule, twelve
         parallel games each, tiers not rankings.
"""

from __future__ import annotations

import random
import sys
import time

from manalab.cards import formats as F
from manalab.cards import precons
from manalab.cards.model import Decklist
from manalab.cards.store import CardStore
from manalab.evaluate.forge_sim import ForgeSimEvaluator
from manalab.search.ports import synergy_score
from manalab.search.report import Measurement, table

COMMANDER = "Goreclaw, Terror of Qal Sisma"
LANDS = 38
QUOTA = {1: 6, 2: 13, 3: 13, 4: 10, 5: 8, 6: 6, 7: 5}   # 61 nonland slots
FORGE_GAMES = 12
PAIRED_SEED = 555        # every candidate plays this exact schedule

STAPLES = [
    "Sol Ring", "Arcane Signet", "Llanowar Elves", "Elvish Mystic",
    "Rampant Growth", "Nature's Lore", "Farseek", "Cultivate",
    "Kodama's Reach", "Sakura-Tribe Elder", "Wood Elves",
    "Beast Whisperer", "Guardian Project", "Harmonize", "Eternal Witness",
    "Beast Within", "Krosan Grip", "Heroic Intervention",
    "Craterhoof Behemoth", "Overrun",
]

PACKAGES = {
    "tokens": ["Avenger of Zendikar", "Rampaging Baloths", "Scute Swarm",
               "Second Harvest", "Parallel Lives", "Tendershoot Dryad"],
    "counters": ["Hardened Scales", "Evolution Sage", "Kami of Whispered Hopes",
                 "Conclave Mentor", "Ozolith, the Shattered Spire", "Bristly Bill, Spine Sower"],
    "landfall": ["Lotus Cobra", "Tireless Provisioner", "Ancient Greenwarden",
                 "Scute Swarm", "Augur of Autumn", "Ramunap Excavator"],
    "stompy": ["Ghalta, Primal Hunger", "Thunderfoot Baloth", "End-Raze Forerunners",
               "Terastodon", "Regal Force", "Nylea, Keen-Eyed"],
}


def main() -> int:
    store = CardStore()
    legal = F.COMMANDER.legal_names(store)
    pool = {}
    for card in store.all_cards():
        if (card.name in legal and card.color_identity
                and set(card.color_identity) <= {"G"}
                and not card.is_land and card.name != COMMANDER):
            pool.setdefault(min(int(card.cmc), 7) or 1, []).append(card.name)
    cards = {c.name: c for c in store.all_cards()}
    cards_by_name = cards

    def bucket_of(name: str) -> int:
        return min(int(cards[name].cmc), 7) or 1

    def fitness(deck_names: frozenset[str], stompy: bool) -> float:
        counts = {n: 1 for n in deck_names}
        counts["Forest"] = LANDS
        score = synergy_score(Decklist(counts), cards_by_name)
        if stompy:
            score += 0.02 * sum((cards[n].base_power or 0)
                                + (cards[n].base_toughness or 0)
                                for n in deck_names if cards[n].is_creature)
        return score

    def make_deck(rng, locked) -> frozenset[str]:
        picked = set(locked)
        for cmc, want in QUOTA.items():
            have = sum(1 for n in picked if bucket_of(n) == cmc)
            options = [n for n in pool.get(cmc, []) if n not in picked]
            rng.shuffle(options)
            picked.update(options[: max(0, want - have)])
        return frozenset(picked)

    def ga(emphasis: str, seed: int) -> frozenset[str]:
        rng = random.Random(seed)
        locked = [n for n in STAPLES + PACKAGES[emphasis] if n in cards]
        stompy = emphasis == "stompy"
        popn = [make_deck(rng, locked) for _ in range(24)]
        for _ in range(60):
            scored = sorted(popn, key=lambda d: -fitness(d, stompy))
            keep = scored[:8]
            children = list(keep)
            while len(children) < 24:
                a, b = rng.sample(keep, 2)
                child = set(locked)
                for cmc, want in QUOTA.items():
                    slot_pool = [n for n in (a | b) if bucket_of(n) == cmc
                                 and n not in child]
                    rng.shuffle(slot_pool)
                    have = sum(1 for n in child if bucket_of(n) == cmc)
                    child.update(slot_pool[: max(0, want - have)])
                    if rng.random() < 0.4:      # mutation: swap one in-bucket
                        swaps = [n for n in pool.get(cmc, []) if n not in child]
                        drops = [n for n in child if bucket_of(n) == cmc
                                 and n not in locked]
                        if swaps and drops:
                            child.discard(rng.choice(drops))
                            child.add(rng.choice(swaps))
                children.append(frozenset(child))
            popn = children
        best = max(popn, key=lambda d: fitness(d, stompy))
        print(f"  {emphasis}: synergy fitness {fitness(best, stompy):.1f}, "
              f"{len(best)} nonland", flush=True)
        return best

    print("stage A+B: GA on the deterministic synergy objective", flush=True)
    champions = {name: ga(name, 100 + i)
                 for i, name in enumerate(PACKAGES)}

    print("\nstage C: paired-seed Forge judgment", flush=True)
    opponents = []
    for d in sorted(precons.commander_precons(), key=lambda x: x["releaseDate"]):
        if d["name"] in ("Rebellion Rising", "Tricky Terrain", "Paradox Power"):
            general, counts = precons.as_decklist(precons.fetch_deck(d["fileName"]))
            opponents.append((d["name"].replace(" ", "")[:12], general, counts))
    forge = ForgeSimEvaluator(opponents, workers=12, clock_seconds=420)

    measurements = []
    for name, deck_names in champions.items():
        counts = {n: 1 for n in deck_names}
        counts["Forest"] = 99 - len(deck_names)
        counts[COMMANDER] = 1
        t0 = time.time()
        res = forge.evaluate(name, COMMANDER, counts,
                             n_games=FORGE_GAMES, seed=PAIRED_SEED)
        measurements.append(Measurement(name, list(res.samples["win_rate"])))
        print(f"  {name}: FULL-RULES {res.metrics['win_rate']:.2f} "
              f"({time.time() - t0:.0f}s)", flush=True)

    print("\n" + table(measurements), flush=True)
    for name, deck_names in champions.items():
        pkg = [n for n in deck_names if n in PACKAGES[name]]
        print(f"{name}: package cards present {pkg}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
