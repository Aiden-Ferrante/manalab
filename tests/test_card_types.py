"""Type lines split into supertypes, card types and subtypes.

The rule matches the one effects.py sets for itself: every word before the dash is
either recognised or recorded as unknown. Card type decides engine behaviour — "is
this a creature" decides whether it can attack — so a type line that half-parses
silently is worse than one that refuses.
"""

from __future__ import annotations

from manalab.cards.types import CARD_TYPES, SUPERTYPES, parse_type_line


def test_the_three_parts_come_apart():
    t = parse_type_line("Legendary Artifact Creature — Golem")
    assert t.supertypes == ("legendary",)
    assert t.card_types == ("artifact", "creature")
    assert t.subtypes == ("Golem",)
    assert t.understood


def test_all_fifteen_card_types_are_known():
    """The comprehensive rules' list. Every one appears in the real corpus."""
    assert CARD_TYPES == {
        "artifact", "battle", "conspiracy", "creature", "dungeon", "enchantment",
        "instant", "kindred", "land", "phenomenon", "plane", "planeswalker",
        "scheme", "sorcery", "vanguard",
    }


def test_the_five_supertypes_are_known():
    assert {"basic", "legendary", "ongoing", "snow", "world"} <= SUPERTYPES


def test_a_line_with_no_subtypes_parses():
    t = parse_type_line("World Enchantment")
    assert t.card_types == ("enchantment",) and t.supertypes == ("world",)
    assert t.subtypes == ()


def test_multiple_supertypes_stack():
    t = parse_type_line("Basic Snow Land — Forest")
    assert t.supertypes == ("basic", "snow")
    assert t.card_types == ("land",)


def test_tribal_is_kindred():
    """Renamed in 2024. Old printings still say Tribal, and they are the same type."""
    assert parse_type_line("Tribal Instant — Elf").card_types == ("kindred", "instant")


def test_summon_is_a_creature():
    """Pre-Sixth-Edition wording. `Summon — Dinosaur` is dashed; `Summon Goblin` is
    not, and its trailing word is a subtype rather than an unrecognised one."""
    assert parse_type_line("Summon — Dinosaur").card_types == ("creature",)
    undashed = parse_type_line("Summon Goblin")
    assert undashed.card_types == ("creature",)
    assert undashed.subtypes == ("Goblin",)
    assert undashed.understood, "the corpus form must not read as a parse failure"


def test_case_is_ignored():
    """`pLAnE — Bad Ass` is a real type line in an Un-set."""
    assert parse_type_line("pLAnE — Bad Ass").card_types == ("plane",)
    assert parse_type_line("instant").card_types == ("instant",)


def test_an_unrecognised_word_is_recorded_not_dropped():
    """Six Un-set cards land here — `Eaturecray — Igpay`, `Phenome-nom`. Silently
    treating them as subtypes would mean the engine could not tell what they are."""
    t = parse_type_line("Eaturecray Creature — Lhurgoyf")
    assert t.card_types == ("creature",)
    assert t.unknown == ("Eaturecray",)
    assert not t.understood


def test_subtypes_are_taken_as_written():
    """There are thousands, they change every set, and validating against a list
    would mean maintaining it forever. An unknown subtype costs nothing."""
    t = parse_type_line("Creature — Wombat Rigger Astronaut")
    assert t.subtypes == ("Wombat", "Rigger", "Astronaut")
    assert t.understood


def test_a_hyphen_inside_a_word_is_not_a_separator():
    """`Phenome-nom` is one word. Splitting on a bare hyphen would make it two."""
    t = parse_type_line("Phenome-nom")
    assert t.subtypes == (), "nothing followed a separator, because there was none"
    assert t.unknown == ("Phenome-nom",)


def test_permanence():
    assert parse_type_line("Creature — Bear").is_permanent
    assert parse_type_line("Legendary Land").is_permanent
    assert not parse_type_line("Instant").is_permanent
    assert not parse_type_line("Sorcery — Arcane").is_permanent
    assert not parse_type_line("Emblem").is_permanent, "not a card, never on the battlefield"


def test_is_a_asks_one_question():
    t = parse_type_line("Artifact Creature — Golem")
    assert t.is_a("creature") and t.is_a("Artifact")
    assert not t.is_a("land")


def test_an_empty_line_is_survivable():
    t = parse_type_line("")
    assert t.card_types == () and t.understood
    assert not t.is_permanent, "no type means nothing to put on the battlefield"


def test_each_face_carries_its_own_types():
    """Brazen Borrower is a Creature on one side and an Instant on the other. The
    joined top-level line says both at once, which is true of the card and of
    neither face."""
    from manalab.cards.model import Face
    front = Face(index=0, name="Brazen Borrower", type_line="Creature — Faerie Rogue")
    back = Face(index=1, name="Petty Theft", type_line="Instant — Adventure")
    assert front.types.card_types == ("creature",) and front.types.is_permanent
    assert back.types.card_types == ("instant",) and not back.types.is_permanent


def test_a_card_groups_under_every_type_it_has():
    """Union across faces: a deckbuilder counting creatures counts Brazen
    Borrower, and one counting instants counts it too."""
    from manalab.cards.model import Card, Face, ManaCost
    card = Card(oracle_id="bb", name="Brazen Borrower // Petty Theft",
                cost=ManaCost(), type_line="Creature // Instant — Adventure",
                faces=(Face(index=0, name="Brazen Borrower",
                            type_line="Creature — Faerie Rogue"),
                       Face(index=1, name="Petty Theft",
                            type_line="Instant — Adventure")))
    assert card.card_types == {"creature", "instant"}
    assert card.is_type("Creature") and card.is_type("instant")
    assert not card.is_type("land")


def test_face_types_lands_in_the_database(tmp_path):
    """The classification must be one GROUP BY away, not a Python property —
    optimization queries the lake, and a property cannot be grouped by in SQL."""
    import gzip, json
    import duckdb
    from manalab.cards import store
    from tests.test_card_faces import DEFAULTS, FACE_DEFAULTS

    def rec(d):
        d = {**DEFAULTS, **d}
        if d.get("card_faces"):
            d["card_faces"] = [{**FACE_DEFAULTS, **x} for x in d["card_faces"]]
        return json.dumps(d)

    src = tmp_path / "c.jsonl.gz"
    with gzip.open(src, "wt") as fh:
        fh.write(rec({"oracle_id": "w", "name": "Wrath", "layout": "normal",
                      "type_line": "Sorcery", "oracle_text": "Destroy all creatures."}) + "\n")
        fh.write(rec({"oracle_id": "bb", "name": "A // B", "layout": "adventure",
                      "type_line": "Creature — Faerie // Instant — Adventure",
                      "card_faces": [
                          {"name": "A", "type_line": "Creature — Faerie",
                           "oracle_text": "Flying"},
                          {"name": "B", "type_line": "Instant — Adventure",
                           "oracle_text": "Draw a card."}]}) + "\n")
    db = tmp_path / "c.duckdb"
    store.build(src, db)
    con = duckdb.connect(str(db), read_only=True)
    try:
        groups = dict(con.execute(
            "SELECT u.t, count(*) FROM face_types, unnest(card_types) AS u(t) "
            "GROUP BY 1").fetchall())
        assert groups == {"sorcery": 1, "creature": 1, "instant": 1}
        perm = dict(con.execute(
            "SELECT f.name, ft.is_permanent FROM face_types ft "
            "JOIN faces f USING (oracle_id, face_index)").fetchall())
        assert perm == {"Wrath": False, "A": True, "B": False}
    finally:
        con.close()
