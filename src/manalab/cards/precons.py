"""Official preconstructed Commander decks, from MTGJSON. Keyless, stdlib-only.

The gauntlet problem: hand-built opponents measure a candidate against decks
nobody plays. WotC's Commander precons are the natural fixed opposition — they
are real products, versioned by release, and every kitchen table has them.
MTGJSON publishes all of them as bulk JSON (MIT-licensed tooling, no key),
which fits the same fetch-to-`data/`, provenance-sidecar pattern as Scryfall.

The honesty requirement travels with the import: a precon contains cards the
engine refuses, and an opponent whose bombs resolve as no-ops is artificially
weak — a bias, not noise, and more games never fix it. So `fidelity_of`
reports the executed fraction of every imported deck, and anything consuming
these as a gauntlet must surface that number beside every result.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Mapping

from manalab.cards.model import Card

DECK_LIST = "https://mtgjson.com/api/v5/DeckList.json"
DECK_URL = "https://mtgjson.com/api/v5/decks/{fileName}.json"
HEADERS = {"User-Agent": "manalab/0.1 (research; deckbuilding simulation)",
           "Accept": "application/json"}


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def fetch_index(data_dir: Path | str = "data") -> list[dict]:
    """Every official deck MTGJSON knows, cached to `data/precons/`."""
    root = Path(data_dir) / "precons"
    root.mkdir(parents=True, exist_ok=True)
    cache = root / "DeckList.json"
    if not cache.exists():
        cache.write_text(json.dumps(_get(DECK_LIST)))
    return json.loads(cache.read_text())["data"]


def commander_precons(data_dir: Path | str = "data") -> list[dict]:
    return [d for d in fetch_index(data_dir) if d.get("type") == "Commander Deck"]


def fetch_deck(file_name: str, data_dir: Path | str = "data") -> dict:
    root = Path(data_dir) / "precons"
    root.mkdir(parents=True, exist_ok=True)
    cache = root / f"{file_name}.json"
    if not cache.exists():
        cache.write_text(json.dumps(_get(DECK_URL.format(fileName=file_name))))
    return json.loads(cache.read_text())["data"]


def as_decklist(deck: dict) -> tuple[str, dict[str, int]]:
    """(commander name, {card name: count}) for one MTGJSON deck payload.

    The commander section can hold partners; the first is taken and the rest
    join the library — a declared simplification, since the engine has one
    command-zone slot per player.
    """
    commanders = deck.get("commander") or []
    if not commanders:
        raise ValueError(f"{deck.get('name')!r} has no commander section")
    counts: dict[str, int] = {}
    for card in list(commanders) + list(deck.get("mainBoard") or []):
        counts[card["name"]] = counts.get(card["name"], 0) + int(card.get("count", 1))
    return commanders[0]["name"], counts


def fidelity_of(counts: Mapping[str, int], cards: Mapping[str, Card]) -> dict:
    """How much of this deck the engine actually executes.

    `known` is cards the store has at all; `faithful` is the executed fraction
    OF THE WHOLE DECK. A precon playing at 0.4 fidelity is an opponent whose
    bombs mostly do nothing, and every win rate against it inherits that bias.
    """
    from manalab.engine import fidelity as F

    total = sum(counts.values())
    known = faithful = 0
    refused: list[str] = []
    for name, count in counts.items():
        card = cards.get(name)
        if card is None:
            refused.append(name)
            continue
        known += count
        if not F.assess(card).reasons:
            faithful += count
        else:
            refused.append(name)
    return {
        "cards": total,
        "known": known / total if total else 0.0,
        "faithful": faithful / total if total else 0.0,
        "refused": tuple(sorted(refused)),
    }
