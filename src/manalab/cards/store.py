"""DuckDB-backed card store.

`data/cards.duckdb` is a build artifact: rebuildable from Scryfall in one
command, never hand-edited, never committed. DuckDB reads the 150 MB Scryfall
JSON directly, so there is no intermediate parsing step in Python.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Iterator, Mapping

import duckdb

from manalab.cards.model import Card, card_from_scryfall

DEFAULT_DB = Path("data/cards.duckdb")

# Only the columns the sim or a legality filter can actually use. Scryfall's
# oracle export has ~80 fields; pulling them all makes the store 10x bigger for
# artist names and border colors.
_COLUMNS = """
    oracle_id, name, mana_cost, cmc, type_line, oracle_text,
    colors, color_identity, produced_mana, legalities, rarity, set_name,
    power, toughness, loyalty, keywords
"""


def build(json_path: Path, db_path: Path = DEFAULT_DB) -> int:
    """Load a Scryfall bulk export into DuckDB. Returns the row count.

    Reads `.jsonl.gz` in place — DuckDB decompresses by file extension, so the
    150 MB uncompressed form never touches disk.
    """
    json_path, db_path = Path(json_path), Path(db_path)
    if not json_path.exists():
        raise FileNotFoundError(f"{json_path} — run `manalab fetch` first")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        con.execute("DROP TABLE IF EXISTS cards")
        con.execute(
            f"""
            CREATE TABLE cards AS
            SELECT {_COLUMNS}
            FROM read_json_auto(
                ?,
                format = 'newline_delimited',
                maximum_object_size = 64000000,
                ignore_errors = false
            )
            -- Tokens, art series and emblems are not playable cards.
            WHERE type_line IS NOT NULL
              AND type_line NOT LIKE 'Token%'
              AND type_line NOT LIKE 'Card%'
            """,
            [str(json_path)],
        )
        con.execute("CREATE INDEX idx_cards_name ON cards(name)")
        (count,) = con.execute("SELECT count(*) FROM cards").fetchone()
        return int(count)
    finally:
        con.close()


class CardStore:
    """Read-only view over the built database.

    Hides the fact that cards came from Scryfall. Swapping in MTGJSON means
    rewriting this module and nothing else.
    """

    def __init__(self, db_path: Path = DEFAULT_DB, *, parse_effects: bool = True) -> None:
        """`parse_effects` attaches parsed oracle-text effects to each card.

        On by default because it costs ~0.08 ms per card and a card without
        effects is inert to the engine. Corpus-wide loads turn it off, since
        `effects.measure` parses for itself and would otherwise do it twice.
        """
        self.parse_effects = parse_effects
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(
                f"{self.db_path} — run `manalab cards build` first"
            )
        self._con = duckdb.connect(str(self.db_path), read_only=True)
        self._cache: dict[str, Card] = {}

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> "CardStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _rows(self, where: str, params: list[object]) -> Iterator[Mapping[str, object]]:
        cur = self._con.execute(f"SELECT {_COLUMNS} FROM cards WHERE {where}", params)
        names = [d[0] for d in cur.description]
        for row in cur.fetchall():
            yield dict(zip(names, row))

    def _build(self, row: Mapping[str, object]) -> Card:
        card = card_from_scryfall(row)
        if not self.parse_effects:
            return card
        from manalab.cards.effects import with_effects

        return with_effects(card)

    def by_name(self, name: str) -> Card:
        """Exact (case-insensitive) name lookup."""
        if name in self._cache:
            return self._cache[name]
        rows = list(self._rows("lower(name) = lower(?)", [name]))
        if not rows:
            raise KeyError(f"no card named {name!r}")
        card = self._build(rows[0])
        self._cache[name] = card
        return card

    def resolve(self, names: Iterable[str]) -> dict[str, Card]:
        """Bulk lookup. Returns a name -> Card map suitable for `game.resolve`."""
        wanted = list(dict.fromkeys(names))
        if not wanted:
            return {}
        placeholders = ",".join("?" * len(wanted))
        rows = list(
            self._rows(f"lower(name) IN ({placeholders})", [n.lower() for n in wanted])
        )
        found = {r["name"]: self._build(r) for r in rows}  # type: ignore[index]

        lowered = {str(k).lower(): v for k, v in found.items()}
        missing = [n for n in wanted if n.lower() not in lowered]
        if missing:
            raise KeyError(f"cards not found: {missing}")
        return {n: lowered[n.lower()] for n in wanted}

    def legal_in(self, fmt: str) -> list[str]:
        """Card names legal in a format, e.g. 'modern', 'commander'."""
        cur = self._con.execute(
            "SELECT name FROM cards WHERE legalities[?] = 'legal' ORDER BY name", [fmt]
        )
        return [r[0] for r in cur.fetchall()]

    def all_cards(self, limit: int | None = None) -> list[Card]:
        """Every card in the store. ~35k objects, a few seconds and ~200 MB.

        For corpus-wide work like effect-parser coverage, where sampling would
        hide exactly the long tail you are trying to measure.
        """
        clause = "TRUE" + (f" LIMIT {int(limit)}" if limit else "")
        return [self._build(row) for row in self._rows(clause, [])]

    def sample(self, n: int, seed: int = 0) -> list[Card]:
        """A deterministic random sample, for quick iteration."""
        rows = self._rows(f"TRUE ORDER BY hash(oracle_id || {int(seed)}) LIMIT {int(n)}", [])
        return [self._build(row) for row in rows]

    def count(self) -> int:
        (n,) = self._con.execute("SELECT count(*) FROM cards").fetchone()
        return int(n)
