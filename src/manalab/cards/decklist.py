"""Reading and writing the standard decklist text format.

    4 Lightning Bolt
    2 Snapcaster Mage
    20 Mountain
    // comments and blank lines are ignored
    Sideboard          <- everything after this marker is skipped in v1

Decklist keys are card *names* throughout v1. Names are what humans type, what
the store indexes, and what round-trips through this format. If double-faced or
alternate-name collisions ever bite, this is the one module that changes.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from manalab.cards.model import Decklist

_LINE = re.compile(r"^\s*(\d+)\s*x?\s+(.+?)\s*$")
_SIDEBOARD = re.compile(r"^\s*(sideboard|//\s*sideboard)\s*:?\s*$", re.I)


def parse(text: str, name: str = "") -> Decklist:
    counts: Counter[str] = Counter()

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//")):
            continue
        if _SIDEBOARD.match(stripped):
            break

        match = _LINE.match(stripped)
        if match is None:
            raise ValueError(f"unparseable decklist line: {line!r}")

        qty, card = match.groups()
        # Strip trailing set/collector annotations: "Lightning Bolt (2XM) 129"
        card = re.sub(r"\s*\([A-Za-z0-9]{2,6}\)\s*[\w-]*$", "", card).strip()
        counts[card] += int(qty)

    return Decklist(dict(counts), name)


def load(path: Path) -> Decklist:
    path = Path(path)
    return parse(path.read_text(encoding="utf-8"), name=path.stem)


def dumps(deck: Decklist) -> str:
    return "\n".join(f"{n} {card}" for card, n in sorted(deck.counts.items()))
