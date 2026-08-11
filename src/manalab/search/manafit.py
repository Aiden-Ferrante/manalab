"""Bilevel mana fitting: the inner problem, solved before evaluation ever runs.

search-problem.md §3(d): given the spells, the land base is a nearly separable
analytic subproblem. Search should never spend simulation budget discovering that
a deck with 30 green pips wants Forests — so every candidate is fitted here,
permanently, and the outer search only ever moves spells and the land *count*.

Scope, stated honestly: basics only, allocated by pip proportion with exact
largest-remainder rounding. That is the Karsten zeroth order — enough to stop
mana-base identity contaminating spell comparisons (the composition-variance
experiment used exactly this rule inline). Nonbasics, duals and utility lands are
a later fidelity, and they belong behind this same interface when they come.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from manalab.cards.model import Card, Decklist
from manalab.evaluate.result import EvalResult, Evaluator

BASICS = {"W": "Plains", "U": "Island", "B": "Swamp",
          "R": "Mountain", "G": "Forest"}
COLORLESS_BASIC = "Wastes"


def pip_profile(spells: Decklist, cards: Mapping[str, Card]) -> dict[str, float]:
    """Colored-pip weight per color, copies included.

    A hybrid pip ({R/G}) contributes fractionally to each of its colors — the
    zeroth-order reading of "either can pay it". Cards missing from `cards` are
    skipped rather than guessed at.
    """
    weight: dict[str, float] = {}
    for name, copies in spells.counts.items():
        card = cards.get(name)
        if card is None:
            continue
        for symbols in card.cost.symbols:
            colored = [c for c in symbols if c in BASICS]
            for color in colored:
                weight[color] = weight.get(color, 0.0) + copies / len(colored)
    return weight


def fit_basics(spells: Decklist, lands: int,
               cards: Mapping[str, Card]) -> Decklist:
    """The spells, plus `lands` basic lands split by pip proportion.

    Exactness rules, each load-bearing:
      * largest-remainder rounding, so the split always sums to `lands` —
        independent rounding drifts by ±1 and a 59-card deck is not a deck;
      * every color with at least one pip gets at least one source, if there are
        lands enough to go around — a proportional split of 23 lands can round a
        two-pip splash to zero, which is a deck that cannot cast two of its
        spells no matter how the shuffles fall;
      * a deck with no colored pips gets Wastes, because zero lands is not a
        mana base and guessing a color would be inventing information.
    """
    if lands < 0:
        raise ValueError("negative land count")
    weight = pip_profile(spells, cards)
    counts = dict(spells.counts)

    if not weight or lands == 0:
        if lands:
            counts[COLORLESS_BASIC] = lands
        return Decklist(counts, name=spells.name)

    colors = sorted(weight, key=lambda c: (-weight[c], c))
    total = sum(weight.values())
    raw = {c: lands * weight[c] / total for c in colors}
    base = {c: int(raw[c]) for c in colors}
    remainder = lands - sum(base.values())
    for c in sorted(colors, key=lambda c: (raw[c] - base[c]), reverse=True)[:remainder]:
        base[c] += 1

    # Min-one guarantee, funded by the largest allocation.
    if lands >= len(colors):
        for c in colors:
            if base[c] == 0:
                donor = max(base, key=base.get)
                base[donor] -= 1
                base[c] += 1

    for c, n in base.items():
        if n:
            counts[BASICS[c]] = counts.get(BASICS[c], 0) + n
    return Decklist(counts, name=spells.name)


@dataclass(frozen=True)
class FittedEvaluator:
    """An Evaluator that mana-fits every deck before its inner evaluator sees it.

    The bilevel fixture as a seam wrapper: search proposes *spells*, the land
    base is derived, and no optimizer anywhere in the stack can waste budget on
    a mana base the hypergeometric distribution already determines. `lands` is
    part of the composition, so the outer search varies it by constructing
    another instance — one line, and it keeps this frozen and shareable.
    """

    inner: Evaluator
    cards: Mapping[str, Card]
    lands: int
    name: str = "mana-fitted"

    def evaluate(self, deck: Decklist, *, n_games: int, seed: int) -> EvalResult:
        return self.inner.evaluate(fit_basics(deck, self.lands, self.cards),
                                   n_games=n_games, seed=seed)
