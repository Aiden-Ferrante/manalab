"""Is what we stored what Scryfall actually says?

The corpus is loaded from a cached bulk export, transformed by SQL, and reshaped
into faces. Every one of those steps can lose or mangle a field quietly, and the
tests cover the *shape* of the result rather than its truth. This checks the truth,
against the source, over a random sample.

    python -u examples/verify_against_scryfall.py [n]

Compares per face: name, type_line, mana_cost, oracle_text, power, toughness,
loyalty. Uses the `/cards/collection` endpoint, which takes 75 identifiers per
request — one request per 75 cards rather than one per card, which is both faster
and the polite way to ask.

A mismatch is not automatically our bug. The bulk file has a date and Scryfall
moves on, so a difference in recent cards may simply be drift. The output says
which fields differ so the two can be told apart.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

from manalab.cards.store import CardStore

ENDPOINT = "https://api.scryfall.com/cards/collection"
HEADERS = {
    "User-Agent": "manalab/0.1 (verification; deckbuilding simulation)",
    "Accept": "application/json",
    "Content-Type": "application/json",
}
BATCH = 75
FIELDS = ("name", "type_line", "mana_cost", "oracle_text", "power", "toughness", "loyalty")


def fetch(oracle_ids: list[str]) -> dict[str, dict]:
    """Cards by oracle_id, in batches. Scryfall asks for a pause between calls."""
    out: dict[str, dict] = {}
    for i in range(0, len(oracle_ids), BATCH):
        chunk = oracle_ids[i:i + BATCH]
        body = json.dumps({"identifiers": [{"oracle_id": o} for o in chunk]}).encode()
        req = urllib.request.Request(ENDPOINT, data=body, headers=HEADERS, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                payload = json.load(r)
        except urllib.error.HTTPError as e:
            print(f"  ! HTTP {e.code} on batch {i // BATCH}", file=sys.stderr)
            continue
        for card in payload.get("data", []):
            out[card["oracle_id"]] = card
        for missing in payload.get("not_found", []):
            print(f"  ! not found upstream: {missing}", file=sys.stderr)
        time.sleep(0.15)
    return out


def faces_of(card: dict) -> list[dict]:
    """Upstream faces, in the same synthesised-face-0 shape the loader produces."""
    if card.get("card_faces"):
        return card["card_faces"]
    return [card]


def norm(value: object) -> str:
    return "" if value is None else str(value)


def main(n: int = 200) -> int:
    store = CardStore(parse_effects=False)
    sample = store.sample(n, seed=7)
    print(f"verifying {len(sample):,} cards against Scryfall\n")

    upstream = fetch([c.oracle_id for c in sample])
    print(f"  fetched {len(upstream):,} of {len(sample):,}\n")

    checked = mismatched = 0
    problems: list[str] = []
    for card in sample:
        remote = upstream.get(card.oracle_id)
        if remote is None:
            continue
        theirs = faces_of(remote)
        if len(theirs) != len(card.faces):
            problems.append(
                f"{card.name}: {len(card.faces)} faces stored, {len(theirs)} upstream")
            mismatched += 1
            continue
        for ours, them in zip(card.faces, theirs):
            checked += 1
            diffs = [f for f in FIELDS if norm(getattr(ours, f, "")) != norm(them.get(f))]
            if diffs:
                mismatched += 1
                for f in diffs:
                    problems.append(
                        f"{card.name} [face {ours.index}] {f}:\n"
                        f"      ours: {norm(getattr(ours, f, ''))[:88]!r}\n"
                        f"      them: {norm(them.get(f))[:88]!r}")

    print(f"  faces compared : {checked:,}")
    print(f"  faces differing: {mismatched:,}")
    if problems:
        print("\n  differences:")
        for p in problems[:40]:
            print(f"    {p}")
        if len(problems) > 40:
            print(f"    … and {len(problems) - 40} more")
    else:
        print("\n  every field matches.")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 200))
