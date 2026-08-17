"""Randomised deck sampling: the design matrix for card-level credit assignment.

A campaign that plays twenty decks a thousand times learns twenty numbers. A
campaign that plays a thousand decks twenty times learns *card* numbers — every
game is 99 cards being played, so if the decks are assembled at random the same
JVM-seconds carry roughly two orders of magnitude more information.

The word doing the work is *randomised*. Because inclusion is decided by a coin
flip rather than by a builder's taste, the coefficients a regression recovers
are causal estimates of a card's marginal contribution, not a record of which
cards good builders happen to like. It is a designed experiment with thousands
of simultaneous arms, and this module is the randomisation.

Two properties are load-bearing, and both cut against making the decks good:

  * **A card in every deck gets no coefficient.** Zero variance, no contrast,
    nothing to estimate. So the staples are randomised too — `core_prob`
    decides how often the ramp package shows up, and setting it to 1.0 buys
    better decks at the price of learning nothing about the cards that matter
    most.
  * **Diversity is the currency.** Deliberately playing mediocre decks widens
    the design matrix, which is what lets the estimator separate one card from
    its neighbours. This is the exact opposite of a genetic algorithm, whose
    whole job is to collapse diversity — and the reason bulk rating and GA
    search want different populations.

The curve template stays a hard constraint: the samples vary in *which* cards
they play, not in whether they can cast them, so mana problems don't smear
across every estimate as noise.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Mapping, Sequence

BUCKET_CAP = 7
"""Everything at seven mana or more shares a bucket — above the curve, the
distinction that matters is castable-at-all, not the exact number."""


@dataclass(frozen=True)
class CurveTemplate:
    """Lands plus a per-mana-value quota. Must total 99 for singleton Commander."""

    lands: int
    quota: Mapping[int, int]

    def __post_init__(self) -> None:
        total = self.lands + sum(self.quota.values())
        if total != 99:
            raise ValueError(
                f"template holds {total} cards; a Commander deck is 99 + commander")

    @property
    def nonland(self) -> int:
        return sum(self.quota.values())


def bucket_of(cmc: float) -> int:
    """Mana value to curve bucket. Zero-cost cards ride with the one-drops."""
    return min(int(cmc), BUCKET_CAP) or 1


def sample_deck(pool: Mapping[int, Sequence[str]], template: CurveTemplate,
                rng: random.Random, *, core: Sequence[str] = (),
                core_prob: float = 0.5,
                core_bucket: Mapping[str, int] | None = None) -> tuple[str, ...]:
    """One randomised deck: `core` cards by coin flip, the rest filled uniformly.

    `core` names are included independently with probability `core_prob` and
    consume their bucket's quota; the remainder of each bucket is drawn without
    replacement from `pool`. Raises if a bucket cannot be filled, which is a
    real error — a template that outruns its pool would otherwise silently
    return short decks and make every downstream count wrong.
    """
    if not 0.0 <= core_prob <= 1.0:
        raise ValueError(f"core_prob must be a probability, got {core_prob}")
    buckets = dict(core_bucket or {})
    picked: set[str] = {name for name in core
                        if name in buckets and rng.random() < core_prob}

    chosen: list[str] = list(picked)
    for cmc, want in sorted(template.quota.items()):
        have = sum(1 for name in picked if buckets.get(name) == cmc)
        need = want - have
        if need < 0:
            raise ValueError(
                f"core cards fill {have} of bucket {cmc}, quota is only {want}")
        options = [name for name in pool.get(cmc, ()) if name not in picked]
        if len(options) < need:
            raise ValueError(
                f"bucket {cmc} needs {need} more cards, pool holds {len(options)}")
        chosen.extend(rng.sample(options, need))

    if len(chosen) != template.nonland:
        raise AssertionError(f"sampled {len(chosen)}, template wants "
                             f"{template.nonland}")
    return tuple(sorted(chosen))


def sample_many(pool: Mapping[int, Sequence[str]], template: CurveTemplate,
                count: int, *, seed: int, core: Sequence[str] = (),
                core_prob: float = 0.5,
                core_bucket: Mapping[str, int] | None = None,
                ) -> list[tuple[str, ...]]:
    """`count` distinct decks. Duplicates are dropped, so the result may be
    shorter — a repeated deck adds games without adding a row of contrast."""
    rng = random.Random(seed)
    seen: dict[tuple[str, ...], None] = {}
    for _ in range(count * 2):
        if len(seen) >= count:
            break
        seen[sample_deck(pool, template, rng, core=core, core_prob=core_prob,
                         core_bucket=core_bucket)] = None
    return list(seen)
