"""The feasible set and how to move around it.

Every deck is an integer vector with `sum(x) == D` and `0 <= x_i <= u_i`. The
sum constraint is what makes the **swap** the natural move: `x_i -= 1; x_j += 1`
lands back in the feasible set exactly, so local search needs no repair operator
and never wastes budget on illegal decks.

Repair exists anyway, because population methods (crossover, CMA-ES rounding)
produce vectors off the constraint surface and have to be projected back.
"""

from __future__ import annotations

import random
from typing import Iterator, Sequence

Vector = tuple[int, ...]


from functools import lru_cache


@lru_cache(maxsize=64)
def _completion_counts(bounds: tuple[int, ...], deck_size: int) -> tuple[tuple[int, ...], ...]:
    """`table[i][r]` = number of feasible ways to fill cards i.. summing to r.

    Exact integer counts (Python ints, so no overflow), computed once per pool
    and cached. This is what makes uniform sampling possible without rejection.
    """
    n = len(bounds)
    table: list[tuple[int, ...]] = [()] * (n + 1)
    table[n] = tuple(1 if r == 0 else 0 for r in range(deck_size + 1))

    for i in range(n - 1, -1, -1):
        nxt = table[i + 1]
        row = []
        for r in range(deck_size + 1):
            row.append(sum(nxt[r - k] for k in range(min(bounds[i], r) + 1)))
        table[i] = tuple(row)
    return tuple(table)


def count_decks(bounds: Sequence[int], deck_size: int) -> int:
    """How many feasible decks exist. Exact, and cheap even when astronomical."""
    return _completion_counts(tuple(bounds), deck_size)[0][deck_size]


def random_feasible(bounds: Sequence[int], deck_size: int, rng: random.Random) -> Vector:
    """A deck drawn **uniformly** from the feasible set.

    Uniformity is not a nicety here. The obvious alternative — deal `deck_size`
    single copies to cards that still have room — is badly non-uniform: it
    concentrates hard on the centre of the simplex and essentially never
    produces a zero count. On a 3-card, 40-copy pool that sampler reached 300 of
    861 feasible decks in 20,000 draws and *never once* reached the optimum,
    which silently turned random search into a measurement of the sampler's bias
    rather than of search difficulty.

    This version walks the cards in order, choosing each count with probability
    proportional to the number of feasible completions it leaves. That is exact
    uniform sampling in O(n * deck_size) after a cached DP, with no rejection.
    """
    bounds_t = tuple(bounds)
    if deck_size > sum(bounds_t):
        raise ValueError(f"deck size {deck_size} exceeds pool capacity {sum(bounds_t)}")

    table = _completion_counts(bounds_t, deck_size)
    if table[0][deck_size] == 0:
        raise ValueError("no feasible deck for these bounds")

    vector: list[int] = []
    remaining = deck_size
    for i, upper in enumerate(bounds_t):
        total = table[i][remaining]
        target = rng.randrange(total)
        for k in range(min(upper, remaining) + 1):
            weight = table[i + 1][remaining - k]
            if target < weight:
                vector.append(k)
                remaining -= k
                break
            target -= weight
        else:  # pragma: no cover - implies the DP disagrees with itself
            raise AssertionError("completion counts inconsistent")

    return tuple(vector)


def spread_feasible(bounds: Sequence[int], deck_size: int, rng: random.Random) -> Vector:
    """Deal single copies to cards with room. Non-uniform by construction.

    Kept because "spread across many cards" is a reasonable *starting point* for
    local search even though it is a terrible sampler. Never use it where
    uniformity is assumed — see `random_feasible`.
    """
    if deck_size > sum(bounds):
        raise ValueError(f"deck size {deck_size} exceeds pool capacity {sum(bounds)}")

    vector = [0] * len(bounds)
    room = [i for i, u in enumerate(bounds) if u > 0]
    for _ in range(deck_size):
        idx = rng.choice(room)
        vector[idx] += 1
        if vector[idx] >= bounds[idx]:
            room.remove(idx)
    return tuple(vector)


def swap(vector: Vector, out_idx: int, in_idx: int) -> Vector:
    """One copy of `out_idx` becomes one copy of `in_idx`. Caller checks bounds."""
    new = list(vector)
    new[out_idx] -= 1
    new[in_idx] += 1
    return tuple(new)


def can_swap(vector: Vector, bounds: Sequence[int], out_idx: int, in_idx: int) -> bool:
    return (
        out_idx != in_idx
        and vector[out_idx] > 0
        and vector[in_idx] < bounds[in_idx]
    )


def swap_neighbors(vector: Vector, bounds: Sequence[int]) -> Iterator[tuple[int, int, Vector]]:
    """Every 1-swap neighbour, as `(out_idx, in_idx, new_vector)`.

    Size is (cards present) x (cards with room) — for a 40-card pool holding 20
    distinct cards that is a few hundred, small enough to enumerate but far too
    many to evaluate at full precision. This is exactly why Phase 3 exists.
    """
    present = [i for i, v in enumerate(vector) if v > 0]
    room = [i for i, v in enumerate(vector) if v < bounds[i]]
    for out_idx in present:
        for in_idx in room:
            if out_idx != in_idx:
                yield out_idx, in_idx, swap(vector, out_idx, in_idx)


def random_swap(vector: Vector, bounds: Sequence[int], rng: random.Random) -> Vector:
    present = [i for i, v in enumerate(vector) if v > 0]
    room = [i for i, v in enumerate(vector) if v < bounds[i]]
    for _ in range(64):
        out_idx, in_idx = rng.choice(present), rng.choice(room)
        if out_idx != in_idx:
            return swap(vector, out_idx, in_idx)
    raise RuntimeError("no legal swap available")


def perturb(vector: Vector, bounds: Sequence[int], k: int, rng: random.Random) -> Vector:
    """`k` successive random swaps. The kick in iterated local search."""
    for _ in range(k):
        vector = random_swap(vector, bounds, rng)
    return vector


def repair(vector: Sequence[int], bounds: Sequence[int], deck_size: int, rng: random.Random) -> Vector:
    """Project an arbitrary integer vector onto the feasible set.

    Clamps to bounds, then adds or removes single copies at random until the
    size is right. Randomised rather than greedy on purpose: a deterministic
    repair biased toward low indices would quietly make the pool's card order
    part of the objective.
    """
    fixed = [max(0, min(int(v), u)) for v, u in zip(vector, bounds)]
    total = sum(fixed)

    while total < deck_size:
        room = [i for i, v in enumerate(fixed) if v < bounds[i]]
        if not room:
            raise ValueError("cannot grow to deck size within bounds")
        fixed[rng.choice(room)] += 1
        total += 1

    while total > deck_size:
        present = [i for i, v in enumerate(fixed) if v > 0]
        fixed[rng.choice(present)] -= 1
        total -= 1

    return tuple(fixed)


def distance(a: Vector, b: Vector) -> int:
    """Number of card slots differing — half the L1 distance, since a swap moves
    one card out and one in."""
    return sum(abs(x - y) for x, y in zip(a, b)) // 2
