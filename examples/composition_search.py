"""Composition-level search on the simplex, mana fitted underneath.

search-problem.md §7.3, running on the architecture the variance experiment
chose: the state is a composition (land count + curve-bucket counts), identity
inside each bucket is sampled with fixed seeds, and every proposed deck reaches
the evaluator through FittedEvaluator — no candidate can be bad at mana, only
bad at composition.

Comparisons are CRN-paired end to end: the same identity seeds and the same
game seed on both sides of every accept/reject, so a move is accepted on the
difference between *compositions*, not between lucky draws.

Honesty note printed with the result: consistency_t4 rewards having 4 mana by
turn 4 and nothing else, so the search is expected to push lands high. Finding
the objective's gameable edge is a correct result — the objective is the thing
under test as much as the searcher (M2_PROMPT Phase 5).

    python -u examples/composition_search.py
"""

from __future__ import annotations

import random
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import composition_variance as cv  # noqa: E402  (pool + buckets, same rules)

from manalab.cards.model import Decklist  # noqa: E402
from manalab.cards.store import CardStore  # noqa: E402
from manalab.evaluate.consistency import ConsistencyEvaluator  # noqa: E402
from manalab.search.manafit import FittedEvaluator  # noqa: E402
from manalab.search.ports import SynergyEvaluator  # noqa: E402
from manalab.search.objective import THROUGHPUT_SYNERGY as OBJECTIVE  # noqa: E402

N_GAMES = 300
M_IDENTITIES = 3
IDENTITY_SEEDS = (1001, 1002, 1003)
SEED_GAMES = 101
PROPOSALS = 80
LANDS_RANGE = (18, 32)


def spells_only(comp: dict[str, int], pool, rng: random.Random) -> Decklist | None:
    """Instantiate the curve buckets, no lands — FittedEvaluator adds those."""
    counts: Counter[str] = Counter()
    for bucket in cv.BUCKETS:
        need = comp[bucket]
        guard = 0
        while need > 0 and guard < 500:
            guard += 1
            card = rng.choice(pool[bucket])
            if counts[card.name] >= 4:
                continue
            counts[card.name] += 1
            need -= 1
        if need > 0:
            return None
    return Decklist(dict(counts))


def evaluate_composition(comp, pool, cards, store) -> float:
    """Mean objective over M identity draws, all seeds fixed (CRN)."""
    scores = []
    for id_seed in IDENTITY_SEEDS:
        deck = spells_only(comp, pool, random.Random(id_seed))
        if deck is None:
            return float("-inf")
        needed = sorted(set(deck.counts) - set(cards))
        if needed:
            cards.update(store.resolve(needed))
        inner = ConsistencyEvaluator(cards=cards)
        fitted = FittedEvaluator(inner=inner, cards=cards, lands=comp["lands"])
        # Synergy outermost: it must see the deck being proposed. Basics carry no
        # ports, so fitting order cannot change the score.
        stack = SynergyEvaluator(inner=fitted, cards=cards)
        scores.append(OBJECTIVE(stack.evaluate(deck, n_games=N_GAMES,
                                               seed=SEED_GAMES)))
    return statistics.mean(scores)


def neighbours(comp: dict[str, int], rng: random.Random) -> dict[str, int]:
    """One step on the simplex: shift a spell between buckets, or trade a land
    for a spell (total stays 60 by construction)."""
    comp = dict(comp)
    kind = rng.random()
    buckets = list(cv.BUCKETS)
    if kind < 0.5:                       # move a spell between buckets
        src = rng.choice([b for b in buckets if comp[b] > 0])
        dst = rng.choice([b for b in buckets if b != src])
        comp[src] -= 1
        comp[dst] += 1
    elif kind < 0.75 and comp["lands"] < LANDS_RANGE[1]:   # spell → land
        src = rng.choice([b for b in buckets if comp[b] > 0])
        comp[src] -= 1
        comp["lands"] += 1
    elif comp["lands"] > LANDS_RANGE[0]:                   # land → spell
        dst = rng.choice(buckets)
        comp[dst] += 1
        comp["lands"] -= 1
    return comp


def show(comp) -> str:
    return (f"lands={comp['lands']:>2}  " +
            " ".join(f"{b}={comp[b]:>2}" for b in cv.BUCKETS))


def main() -> int:
    rng = random.Random(11)
    store = CardStore()
    pool = cv.build_pool(store)
    # The fitter appends basics the spell decklists never mention, so the card
    # mapping must know them before the first evaluate — found the hard way.
    cards: dict = dict(store.resolve(["Mountain", "Forest"]))

    current = cv.sample_composition(rng)
    current_f = evaluate_composition(current, pool, cards, store)
    best, best_f = dict(current), current_f
    print(f"start    {show(current)}   f={current_f:.4f}")

    accepted = 0
    for step in range(PROPOSALS):
        candidate = neighbours(current, rng)
        f = evaluate_composition(candidate, pool, cards, store)
        if f > current_f:
            current, current_f = candidate, f
            accepted += 1
            marker = ""
            if f > best_f:
                best, best_f = dict(candidate), f
                marker = "  ← best"
            print(f"step {step:>3} {show(current)}   f={f:.4f}{marker}")

    print()
    print(f"proposals {PROPOSALS} · accepted {accepted}")
    print(f"best     {show(best)}   f={best_f:.4f}")

    print()
    print("context — hand-picked compositions on the same seeds:")
    for label, comp in [
        ("24 lands, balanced", {"lands": 24, "c1": 7, "c2": 8, "c3": 8, "c4": 7, "c5": 6}),
        ("20 lands, aggro", {"lands": 20, "c1": 12, "c2": 12, "c3": 10, "c4": 4, "c5": 2}),
        ("28 lands, top-heavy", {"lands": 28, "c1": 2, "c2": 4, "c3": 6, "c4": 8, "c5": 12}),
    ]:
        f = evaluate_composition(comp, pool, cards, store)
        print(f"  {label:<22} {show(comp)}   f={f:.4f}")

    print()
    print("throughput pays only for mana actually spent on spells, so lands have")
    print("an interior optimum — watch whether the climb finds it rather than a rail.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
