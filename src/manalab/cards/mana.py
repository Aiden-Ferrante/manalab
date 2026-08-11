"""Mana cost parsing.

A cost is `generic` colorless mana plus a sequence of `symbols`, where each
symbol is the *set of colors that can satisfy it*. That representation collapses
plain and hybrid pips into one thing:

    {W}    -> frozenset({"W"})
    {W/U}  -> frozenset({"W", "U"})

which means the payment solver in `game.mana` only ever solves one problem
(bipartite matching) instead of special-casing hybrids.

Known approximations, all deliberate:
  - {2/W} monocolored-hybrid is treated as {W}. The "pay 2 generic instead"
    branch is not modeled.
  - {W/P} Phyrexian is treated as {W}. Paying life is not modeled.
  - {X} is captured in `x_count` and contributes 0 to a cost's payability.
Each is recorded on the cost so callers can filter decks that lean on them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

COLORS = ("W", "U", "B", "R", "G")

_SYMBOL = re.compile(r"\{([^}]+)\}")


@dataclass(frozen=True)
class ManaCost:
    generic: int = 0
    symbols: tuple[frozenset[str], ...] = ()
    x_count: int = 0
    approximated: bool = False
    """True if parsing dropped a mode (monocolor hybrid, Phyrexian)."""

    @property
    def cmc(self) -> int:
        """Converted mana cost. X counts as 0, matching Magic's own rule."""
        return self.generic + len(self.symbols)

    @property
    def pips(self) -> int:
        """Number of colored symbols. The quantity Karsten-style math cares about."""
        return len(self.symbols)

    def pip_count(self, color: str) -> int:
        """Symbols that *require* `color` — hybrids don't count, they have an out."""
        return sum(1 for s in self.symbols if s == {color})

    @property
    def colors(self) -> frozenset[str]:
        return frozenset().union(*self.symbols) if self.symbols else frozenset()

    def __str__(self) -> str:
        parts = []
        if self.x_count:
            parts.append("{X}" * self.x_count)
        if self.generic:
            parts.append(f"{{{self.generic}}}")
        for s in self.symbols:
            parts.append("{" + "/".join(sorted(s)) + "}")
        return "".join(parts) or "{0}"


def parse_cost(mana_cost: str | None) -> ManaCost:
    """Parse a Scryfall `mana_cost` string such as `"{2}{W}{W}"`.

    Lands and other costless cards have `None` or `""`, which parse to {0}.
    """
    if not mana_cost:
        return ManaCost()

    generic = 0
    symbols: list[frozenset[str]] = []
    x_count = 0
    approximated = False

    for raw in _SYMBOL.findall(mana_cost):
        token = raw.upper()

        if token.isdigit():
            generic += int(token)
            continue
        if token == "X":
            x_count += 1
            continue

        parts = token.split("/")
        colors = {p for p in parts if p in COLORS}

        # {C} colorless-specific behaves as generic for our purposes.
        if not colors and parts == ["C"]:
            generic += 1
            continue

        # {W/P} phyrexian and {2/W} monocolor hybrid both lose a payment mode.
        if "P" in parts or any(p.isdigit() for p in parts):
            approximated = True

        if not colors:
            # Unrecognized symbol (snow, energy, ...). Treat as generic, loudly.
            generic += 1
            approximated = True
            continue

        symbols.append(frozenset(colors))

    return ManaCost(
        generic=generic,
        symbols=tuple(symbols),
        x_count=x_count,
        approximated=approximated,
    )


def parse_produced(produced_mana: list[str] | None) -> frozenset[str]:
    """Colors a permanent can produce, from Scryfall's `produced_mana`.

    Colorless-only producers yield an empty set, which the payment solver reads
    as "pays generic costs only".
    """
    if not produced_mana:
        return frozenset()
    return frozenset(c.upper() for c in produced_mana if c.upper() in COLORS)
