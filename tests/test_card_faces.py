"""The faces table: one row per printed side, built from a real JSONL file.

A card's text lives on its faces. Reading the top-level `oracle_text` instead left
886 of the 35,139 loaded cards silently textless — every transform, adventure,
split, modal DFC and flip card — because Scryfall sets that field to null whenever
`card_faces` is present.

Fixtures are written as gzipped JSONL and built with the real loader, because the
thing under test is the SQL, and a hand-built dict would test nothing.
"""

from __future__ import annotations

import gzip
import json

import duckdb
import pytest

from manalab.cards import store

SINGLE = {
    "oracle_id": "bolt", "name": "Lightning Bolt", "layout": "normal",
    "mana_cost": "{R}", "cmc": 1.0, "type_line": "Instant",
    "oracle_text": "Lightning Bolt deals 3 damage to any target.",
}
VANILLA = {
    "oracle_id": "bear", "name": "Grizzly Bears", "layout": "normal",
    "mana_cost": "{1}{G}", "cmc": 2.0, "type_line": "Creature — Bear",
    "oracle_text": "", "power": "2", "toughness": "2",
}
# The shape that broke everything: text on the faces, null at the top.
TRANSFORM = {
    "oracle_id": "captive", "name": "Ulvenwald Captive // Ulvenwald Abomination",
    "layout": "transform", "cmc": 2.0, "mana_cost": None, "oracle_text": None,
    "type_line": "Creature — Werewolf Horror // Creature — Eldrazi Werewolf",
    "card_faces": [
        {"name": "Ulvenwald Captive", "mana_cost": "{1}{G}",
         "type_line": "Creature — Werewolf Horror", "power": "1", "toughness": "2",
         "oracle_text": "Defender\n{T}: Add {G}."},
        # The back face has no cost because it is never cast — that is not missing
        # data, and a loader that treats "" as absent would be wrong here.
        {"name": "Ulvenwald Abomination", "mana_cost": "",
         "type_line": "Creature — Eldrazi Werewolf", "power": "4", "toughness": "6",
         "oracle_text": "{T}: Add {C}{C}."},
    ],
}
SPLIT_FIVE = {
    "oracle_id": "who", "name": "Who // What // When // Where // Why",
    "layout": "split", "cmc": 0.0, "mana_cost": "{1}{W} // {2}{U}",
    "type_line": "Instant // Instant // Instant // Instant // Instant",
    "oracle_text": None,
    "card_faces": [{"name": n, "mana_cost": "{1}{W}", "type_line": "Instant",
                    "oracle_text": f"{n} does a thing."}
                   for n in ("Who", "What", "When", "Where", "Why")],
}
TOKEN = {
    "oracle_id": "tok", "name": "Soldier", "layout": "token",
    "type_line": "Token Creature — Soldier", "oracle_text": "",
}


# read_json_auto infers the schema from the rows it is given, and the loader selects
# every column a real Scryfall record carries — so a fixture missing them fails to
# bind rather than testing anything. Defaults keep each record above about its own
# concern instead of restating seventeen fields five times.
DEFAULTS = {
    "mana_cost": None, "cmc": 0.0, "oracle_text": None, "layout": "normal",
    "colors": [], "color_identity": [], "produced_mana": None,
    "legalities": {"standard": "not_legal"}, "rarity": "common",
    "set_name": "Testing", "power": None, "toughness": None, "loyalty": None,
    "keywords": [], "card_faces": None,
}


# Every face carries the same keys, because DuckDB infers a struct's shape from the
# data and narrows to the fields all rows share — give one face `loyalty` and another
# not, and the column stops binding. Real Scryfall faces are uniform, which is why
# this only bites in fixtures, but it is the reason they must be uniform too.
FACE_DEFAULTS = {
    "name": "", "mana_cost": None, "type_line": "", "oracle_text": None,
    "power": None, "toughness": None, "loyalty": None,
}


def record(rec: dict) -> str:
    rec = {**DEFAULTS, **rec}
    if rec.get("card_faces"):
        rec["card_faces"] = [{**FACE_DEFAULTS, **face} for face in rec["card_faces"]]
    return json.dumps(rec)


@pytest.fixture
def built(tmp_path):
    src = tmp_path / "cards.jsonl.gz"
    with gzip.open(src, "wt") as fh:
        for rec in (SINGLE, VANILLA, TRANSFORM, SPLIT_FIVE, TOKEN):
            fh.write(record(rec) + "\n")
    db = tmp_path / "cards.duckdb"
    store.build(src, db)
    con = duckdb.connect(str(db), read_only=True)
    yield con
    con.close()


def one(con, sql, *params):
    return con.execute(sql, list(params)).fetchone()[0]


def test_every_card_has_at_least_one_face(built):
    """The invariant the whole design rests on: downstream code reads faces and
    never has to branch on layout."""
    assert one(built, """SELECT count(*) FROM cards c
        WHERE NOT EXISTS (SELECT 1 FROM faces f WHERE f.oracle_id = c.oracle_id)""") == 0


def test_no_face_is_orphaned(built):
    assert one(built, """SELECT count(*) FROM faces f
        WHERE NOT EXISTS (SELECT 1 FROM cards c WHERE c.oracle_id = f.oracle_id)""") == 0


def test_a_single_faced_card_gets_one_synthesised_face(built):
    assert one(built, "SELECT count(*) FROM faces WHERE oracle_id = 'bolt'") == 1
    assert one(built, "SELECT face_index FROM faces WHERE oracle_id = 'bolt'") == 0
    assert one(built, "SELECT oracle_text FROM faces WHERE oracle_id = 'bolt'") \
        == SINGLE["oracle_text"]


def test_face_text_is_reachable_where_the_top_level_is_null(built):
    """The bug this table exists for. `Ulvenwald Captive` has two real abilities and
    a null top-level oracle_text, so before faces it read as a vanilla card."""
    assert one(built, "SELECT oracle_text FROM cards WHERE oracle_id = 'captive'") is None
    texts = [r[0] for r in built.execute(
        "SELECT oracle_text FROM faces WHERE oracle_id='captive' ORDER BY face_index").fetchall()]
    assert texts == ["Defender\n{T}: Add {G}.", "{T}: Add {C}{C}."]


def test_faces_keep_their_order(built):
    names = [r[0] for r in built.execute(
        "SELECT name FROM faces WHERE oracle_id='who' ORDER BY face_index").fetchall()]
    assert names == ["Who", "What", "When", "Where", "Why"], \
        "face_index is the printed order, not whatever the unnest happened to yield"


def test_a_back_face_with_no_cost_keeps_its_empty_string(built):
    """`''` means "this face has no cost" — it is never cast. Collapsing it to NULL
    would lose the distinction from a face whose cost we simply failed to read."""
    assert one(built, """SELECT mana_cost FROM faces
        WHERE oracle_id='captive' AND face_index=1""") == ""


def test_per_face_power_and_toughness_survive(built):
    assert built.execute("""SELECT power, toughness FROM faces
        WHERE oracle_id='captive' ORDER BY face_index""").fetchall() == [("1", "2"), ("4", "6")]


def test_tokens_are_excluded_from_both_tables(built):
    assert one(built, "SELECT count(*) FROM cards WHERE oracle_id='tok'") == 0
    assert one(built, "SELECT count(*) FROM faces WHERE oracle_id='tok'") == 0


def test_a_vanilla_card_still_gets_a_face(built):
    """Textless is not faceless. 350 real cards are genuinely vanilla and they must
    still join cleanly, or every downstream query needs an outer join."""
    assert one(built, "SELECT count(*) FROM faces WHERE oracle_id='bear'") == 1
    assert one(built, "SELECT oracle_text FROM faces WHERE oracle_id='bear'") == ""


def test_rebuilding_is_idempotent(tmp_path):
    """Runs the loader twice over one source. Owns its own connections rather than
    taking the fixture's — DuckDB refuses a writable handle while a read-only one is
    open on the same file, so a rebuild test cannot borrow a reader."""
    src = tmp_path / "cards.jsonl.gz"
    with gzip.open(src, "wt") as fh:
        for rec in (SINGLE, VANILLA, TRANSFORM, SPLIT_FIVE, TOKEN):
            fh.write(record(rec) + "\n")
    db = tmp_path / "twice.duckdb"

    def counts():
        store.build(src, db)
        con = duckdb.connect(str(db), read_only=True)
        try:
            return (one(con, "SELECT count(*) FROM cards"),
                    one(con, "SELECT count(*) FROM faces"),
                    one(con, "SELECT count(*) FROM (SELECT DISTINCT * FROM faces)"))
        finally:
            con.close()

    first = counts()
    assert counts() == first, "a second load must not duplicate or drop rows"


def test_tags_are_optional_and_exploded(tmp_path):
    """oracle_tags is a second bulk file, present or not. Absent: the build still
    succeeds and the tables are simply empty-handed. Present: one record per tag
    explodes into (oracle_id, tag) rows, one GROUP BY away like face_types."""
    src = tmp_path / "cards.jsonl.gz"
    with gzip.open(src, "wt") as fh:
        fh.write(record(SINGLE) + "\n")
    db = tmp_path / "cards.duckdb"
    store.build(src, db)                      # no tags file beside it
    con = duckdb.connect(str(db), read_only=True)
    try:
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        assert "card_tags" not in tables, "no file, no table — not an empty lie"
    finally:
        con.close()

    tags = tmp_path / "oracle_tags.jsonl.gz"
    with gzip.open(tags, "wt") as fh:
        fh.write(json.dumps({
            "object": "tag", "slug": "removal", "label": "Removal",
            "description": "Gets rid of things.", "parent_ids": [],
            "taggings": [{"oracle_id": "bolt", "weight": "median"}],
        }) + "\n")
    store.build(src, db)
    con = duckdb.connect(str(db), read_only=True)
    try:
        rows = con.execute("SELECT oracle_id, tag FROM card_tags").fetchall()
        assert rows == [("bolt", "removal")]
        assert con.execute("SELECT card_count FROM tags").fetchone()[0] == 1
    finally:
        con.close()
