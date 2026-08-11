"""The architecture-deciding experiment: composition or identity?

docs/search-problem.md §6. The claim under test:

    Most of the variance in f across legal decks is explained by composition
    (role counts), not by card identity within roles.

If composition dominates, deck search collapses to a low-dimensional simplex
walk with an assignment step after it. If identity dominates, the synergy
hypergraph is load-bearing and composition is just a constraint. One number
decides which column of the framework table leads.

Design: K compositions × M identity-instantiations per composition, every deck
evaluated on the same seed (CRN — decks see identical shuffles, so between-deck
differences are differences in the deck). The composition here is what the
goldfish objective can plausibly respond to: land count and the mana curve.
Lands are Karsten-fitted basics (split by pip proportion), so mana-base identity
is removed as a confounder rather than left as noise.

The simulator's own noise would otherwise masquerade as identity variance, so it
is estimated directly — a subset of decks is re-evaluated on a second seed and
Var(f₁−f₂)/2 estimates the per-deck noise floor — and subtracted.

    python -u examples/composition_variance.py
"""

from __future__ import annotations

import random
import statistics
from collections import Counter

from manalab.cards.model import Decklist
from manalab.cards.store import CardStore
from manalab.evaluate.consistency import ConsistencyEvaluator
from manalab.search.objective import CONSISTENCY

K_COMPOSITIONS = 48
M_IDENTITIES = 6
N_GAMES = 300
SEED_CRN = 101       # every deck sees these shuffles
SEED_NOISE = 202     # second reading for the noise floor
NOISE_DECKS = 32
BUCKETS = ("c1", "c2", "c3", "c4", "c5")   # cmc ≤1, 2, 3, 4, ≥5


def bucket_of(cmc: float) -> str:
    return BUCKETS[min(max(int(cmc), 1), 5) - 1]


def build_pool(store: CardStore):
    """RG spells across all formats, bucketed by curve slot.

    Not format-filtered: a legality filter was drafted here and silently did
    nothing — Card carries no legalities field — so the honest description is
    the broad pool, which if anything makes the composition result *more*
    general, not less."""
    pool: dict[str, list] = {b: [] for b in BUCKETS}
    for card in store.all_cards():
        if card.is_land or not card.faces:
            continue
        types = card.card_types
        if not types or not types & {"creature", "instant", "sorcery",
                                     "artifact", "enchantment", "planeswalker"}:
            continue
        if not card.color_identity or not card.color_identity <= {"R", "G"}:
            continue
        if card.cost.approximated or card.cost.cmc > 7 or card.cost.pips == 0:
            continue
        pool[bucket_of(card.cost.cmc)].append(card)
    return pool


def sample_composition(rng: random.Random) -> dict[str, int]:
    lands = rng.randint(20, 27)
    spells = 60 - lands
    weights = [rng.random() + 0.15 for _ in BUCKETS]
    total = sum(weights)
    counts = [int(spells * w / total) for w in weights]
    while sum(counts) < spells:
        counts[rng.randrange(len(counts))] += 1
    return {"lands": lands, **dict(zip(BUCKETS, counts))}


def instantiate(comp: dict[str, int], pool, rng: random.Random) -> Decklist | None:
    """Fill each curve slot with ≤4-of picks, then Karsten-fit basic lands."""
    counts: Counter[str] = Counter()
    r_pips = g_pips = 0
    for b in BUCKETS:
        need = comp[b]
        candidates = pool[b]
        guard = 0
        while need > 0 and guard < 500:
            guard += 1
            card = rng.choice(candidates)
            if counts[card.name] >= 4:
                continue
            counts[card.name] += 1
            need -= 1
            for syms in card.cost.symbols:
                if "R" in syms:
                    r_pips += 1
                if "G" in syms:
                    g_pips += 1
        if need > 0:
            return None
    lands = comp["lands"]
    pips = max(r_pips + g_pips, 1)
    mountains = round(lands * r_pips / pips)
    mountains = min(max(mountains, 1 if r_pips else 0), lands - (1 if g_pips else 0))
    counts["Mountain"] = mountains
    counts["Forest"] = lands - mountains
    return Decklist(dict(counts))


def main() -> int:
    rng = random.Random(7)
    store = CardStore()
    pool = build_pool(store)
    print("pool per bucket :", {b: len(cs) for b, cs in pool.items()})

    decks: list[tuple[int, Decklist]] = []
    for k in range(K_COMPOSITIONS):
        comp = sample_composition(rng)
        made = 0
        while made < M_IDENTITIES:
            deck = instantiate(comp, pool, rng)
            if deck is not None:
                decks.append((k, deck))
                made += 1
    print(f"decks           : {len(decks)}  "
          f"({K_COMPOSITIONS} compositions × {M_IDENTITIES} identities)")

    names = sorted({n for _, d in decks for n in d.counts})
    cards = store.resolve(names)
    evaluator = ConsistencyEvaluator(cards=cards)

    scores: dict[int, list[float]] = {}
    flat: list[tuple[int, int, float]] = []
    for i, (k, deck) in enumerate(decks):
        result = evaluator.evaluate(deck, n_games=N_GAMES, seed=SEED_CRN)
        f = CONSISTENCY(result)
        scores.setdefault(k, []).append(f)
        flat.append((i, k, f))
        if i % 48 == 0:
            print(f"  … {i}/{len(decks)}")

    # Noise floor: same decks, different shuffles; Var(f1 − f2)/2.
    diffs = []
    for i, k, f1 in flat[:NOISE_DECKS]:
        result = evaluator.evaluate(decks[i][1], n_games=N_GAMES, seed=SEED_NOISE)
        diffs.append(f1 - CONSISTENCY(result))
    noise_var = statistics.variance(diffs) / 2 if len(diffs) > 1 else 0.0

    group_means = [statistics.mean(v) for v in scores.values()]
    ms_within = statistics.mean(
        statistics.variance(v) for v in scores.values() if len(v) > 1)
    var_between_means = statistics.variance(group_means)
    # One-way ANOVA, balanced design: E[Var(group means)] = σ²_comp + MS_within/M.
    var_comp = max(0.0, var_between_means - ms_within / M_IDENTITIES)
    var_identity = max(0.0, ms_within - noise_var)
    total = var_comp + var_identity

    print()
    print(f"objective            : {CONSISTENCY.name}  (n={N_GAMES} games, CRN)")
    print(f"grand mean           : {statistics.mean(f for _, _, f in flat):.4f}")
    print(f"noise floor (var)    : {noise_var:.6f}")
    print(f"σ² composition       : {var_comp:.6f}")
    print(f"σ² identity          : {var_identity:.6f}")
    if total > 0:
        share = var_comp / total
        print(f"composition share    : {share:.1%}   (of explainable variance)")
        print()
        if share >= 0.7:
            print("verdict: COMPOSITION-DOMINANT — search the simplex first;")
            print("         identity refines within winning compositions.")
        elif share <= 0.3:
            print("verdict: IDENTITY-DOMINANT — the synergy hypergraph is")
            print("         load-bearing; composition is a constraint, not a map.")
        else:
            print("verdict: MIXED — two-level search stands, but identity terms")
            print("         must enter earlier than the pure-simplex plan assumed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
