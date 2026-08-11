"""Can this cost be paid from these sources?

Lives in L0 rather than in either game model. Both `manalab.game` and
`manalab.engine` need it and are forbidden from importing each other, but the
question "does this multiset of mana sources cover this cost" is a property of
`ManaCost` alone — it knows nothing about turns, zones, or priority. Duplicating
it in both models would be the classic way for two implementations to drift
apart on exactly the interactions that matter.

The naive version of this ("count blue sources, is it >= blue pips") is wrong
whenever duals exist: two Steam Vents can pay {U}{R} but not {U}{U}. Get this
wrong and every mana-base conclusion the tool produces is wrong.

The correct formulation is bipartite matching. Each colored symbol is a left
node, each untapped source a right node, an edge exists when the source can
produce a color the symbol accepts. The cost is payable iff there is a matching
saturating every symbol, with enough sources left over to cover generic.

Sizes here are tiny (<= ~10 symbols, <= ~20 sources), so Kuhn's algorithm is
more than fast enough and far easier to verify than Hopcroft-Karp.
"""

from __future__ import annotations

from typing import Sequence

from manalab.cards.mana import ManaCost

Source = frozenset[str]
"""Colors one untapped permanent can produce. Empty means colorless-only."""


def assign(cost: ManaCost, sources: Sequence[Source]) -> tuple[int, ...] | None:
    """Return the indices of sources spent paying `cost`, or None if unpayable.

    The returned tuple has length `cost.cmc`. Sources not in it remain untapped,
    which is what lets the sim cast several spells in one turn.
    """
    need = cost.generic + len(cost.symbols)
    if need == 0:
        return ()
    if len(sources) < need:
        return None

    match_for_source: list[int | None] = [None] * len(sources)

    for symbol_idx in range(len(cost.symbols)):
        seen = [False] * len(sources)
        if not _augment(symbol_idx, cost.symbols, sources, seen, match_for_source):
            return None

    used = [i for i, m in enumerate(match_for_source) if m is not None]

    # Pay generic with the least flexible sources left, so that colored
    # requirements later in the same turn keep the widest options. A
    # colorless-only source produces no colors at all, so it is the first thing
    # generic should consume.
    leftover = [i for i, m in enumerate(match_for_source) if m is None]
    leftover.sort(key=lambda i: (len(sources[i]), i))
    used.extend(leftover[: cost.generic])

    return tuple(sorted(used))


def _augment(
    symbol_idx: int,
    symbols: Sequence[Source],
    sources: Sequence[Source],
    seen: list[bool],
    match_for_source: list[int | None],
) -> bool:
    """Standard Kuhn augmenting-path step for one colored symbol."""
    accepts = symbols[symbol_idx]
    for src_idx, produces in enumerate(sources):
        if seen[src_idx] or not (produces & accepts):
            continue
        seen[src_idx] = True
        holder = match_for_source[src_idx]
        if holder is None or _augment(holder, symbols, sources, seen, match_for_source):
            match_for_source[src_idx] = symbol_idx
            return True
    return False


def can_pay(cost: ManaCost, sources: Sequence[Source]) -> bool:
    return assign(cost, sources) is not None
