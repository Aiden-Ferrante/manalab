"""Every card, every face, every field — the exhaustive transformation check.

The sampled verifier (`verify_against_scryfall.py`) answers "is the bulk file
current" with a few hundred API calls. This answers a different question with no
network at all: is the database an *exact* transformation of that file? The bulk
export is Scryfall's own; comparing all of it is free, so nothing is sampled.

    python -u examples/verify_exact.py

Three checks, and the third is the one comparison alone cannot make:

  1. Stored fields — every card and every face, field by field against the source.
  2. Membership — nothing missing, nothing extra, filter accounted for.
  3. Derived fields — `produces` and `taps_for_mana` are manalab's own inference,
     so they are checked against invariants instead: every disagreement with
     `produced_mana` must be one of the two documented designs (colors-only
     filtering; fetchland inference), and every source-attested producer must be
     visible to the payment solver.

Exit code 0 means exact. Anything else prints what broke, and how.
"""

from __future__ import annotations

import gzip
import json
import sys

import duckdb

from manalab.cards.store import DEFAULT_DB, CardStore, is_playable

BULK = "data/oracle_cards.jsonl.gz"

CARD_FIELDS = ("name", "layout", "cmc", "type_line", "oracle_text",
               "mana_cost", "power", "toughness", "loyalty")
FACE_FIELDS = ("name", "mana_cost", "type_line", "oracle_text",
               "power", "toughness", "loyalty")


def norm(v: object) -> str:
    return "" if v is None else str(v)


def playable(card: dict) -> bool:
    """Which source rows the store was supposed to keep.

    Imported rather than restated. This was a third copy of the loader's WHERE
    clause, and when the store gained a legality filter this script kept checking
    against the old rule and reported 3,264 phantom diffs — a verifier failing
    because it disagreed with the thing it verifies, not because anything was
    wrong with the data.
    """
    return is_playable(card)


def main() -> int:
    con = duckdb.connect(str(DEFAULT_DB), read_only=True)
    db_cards: dict[str, tuple] = {}
    for row in con.execute(
            f"SELECT oracle_id, {', '.join(CARD_FIELDS)} FROM cards").fetchall():
        db_cards[str(row[0])] = row[1:]
    db_faces: dict[str, list[tuple]] = {}
    for row in con.execute(
            f"SELECT oracle_id, face_index, {', '.join(FACE_FIELDS)} "
            "FROM faces ORDER BY oracle_id, face_index").fetchall():
        db_faces.setdefault(str(row[0]), []).append(row[2:])

    problems: list[str] = []
    seen: set[str] = set()
    checked = 0

    for line in gzip.open(BULK, "rt"):
        card = json.loads(line)
        if not playable(card):
            continue
        checked += 1
        oid = card["oracle_id"]
        seen.add(oid)

        stored = db_cards.get(oid)
        if stored is None:
            problems.append(f"missing from db: {card['name']}")
            continue
        for field, ours in zip(CARD_FIELDS, stored):
            if norm(ours) != norm(card.get(field)):
                problems.append(f"{card['name']}.{field}: "
                                f"{norm(ours)[:40]!r} != {norm(card.get(field))[:40]!r}")

        src_faces = card.get("card_faces") or [card]
        ours_faces = db_faces.get(oid, [])
        if len(src_faces) != len(ours_faces):
            problems.append(
                f"{card['name']}: {len(ours_faces)} faces stored, {len(src_faces)} in source")
            continue
        for i, (stored_face, src_face) in enumerate(zip(ours_faces, src_faces)):
            for field, ours in zip(FACE_FIELDS, stored_face):
                if norm(ours) != norm(src_face.get(field)):
                    problems.append(f"{card['name']}[{i}].{field}: "
                                    f"{norm(ours)[:40]!r} != {norm(src_face.get(field))[:40]!r}")

    extra = set(db_cards) - seen
    for oid in list(extra)[:5]:
        problems.append(f"in db but not in source: {db_cards[oid][0]}")

    print(f"  cards checked      : {checked:,}")
    print(f"  stored-field diffs : {len(problems)}")

    # --- derived fields -------------------------------------------------
    produced: dict[str, list[str]] = {}
    for line in gzip.open(BULK, "rt"):
        card = json.loads(line)
        produced[card["oracle_id"]] = card.get("produced_mana") or []

    store = CardStore(parse_effects=False)
    fetch_ok = colorless_ok = agree = 0
    for card in store.all_cards():
        theirs = frozenset(c.upper() for c in produced.get(card.oracle_id, []))
        colors_only = frozenset(c for c in theirs if c in "WUBRG")
        if card.produces == theirs:
            agree += 1
        elif card.produces == colors_only:
            colorless_ok += 1        # documented: colors-only, C filtered
        elif not theirs and card.produces and "Search your library" in "".join(
                f.oracle_text for f in card.faces):
            fetch_ok += 1            # documented: fetchland inference
        else:
            problems.append(f"produces unexplained: {card.name} "
                            f"ours={sorted(card.produces)} src={sorted(theirs)}")
        if theirs and not card.taps_for_mana:
            problems.append(f"attested producer invisible: {card.name}")

    print(f"  produces           : {agree:,} exact · {colorless_ok:,} colors-only by design"
          f" · {fetch_ok} fetchland by design")

    if problems:
        print(f"\n  NOT EXACT — {len(problems)} problems:")
        for p in problems[:30]:
            print(f"    {p}")
        return 1
    print("\n  exact: every stored field matches the source, and every derived"
          "\n  disagreement is one of the two documented designs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
