"""Deep-queue bulk runner: many decks, few games each, every slot always full.

The campaigns so far measured ~100 games/hour and blamed the JVM. They were
measuring a *batch*: twelve games in twelve slots means eleven finished workers
waiting on the slowest game, so the observed rate tracked the straggler rather
than the game. A deep queue removes that entirely — one work item is one deck
against one table, hundreds are queued at once, and a slot that frees takes the
next item instead of idling. Throughput then tracks the MEAN game, and the
stall-prone tail costs one slot rather than the whole batch.

Every result is written to sqlite as it lands, so a run that dies at hour six
keeps its first six hours, and re-running skips what is already stored. Games
accumulate into an asset: the rows are the training set the ratings estimator
reads, and they never need to be played twice.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from manalab.evaluate.forge_sim import TOTAL_JVMS, ForgeSimEvaluator

DEFAULT_DB = Path("data/bulk_games.sqlite")
_WRITE_LOCK = threading.Lock()


@dataclass(frozen=True)
class Table:
    """A named three-opponent field. The label is part of every stored row so
    a table effect can be modelled later instead of averaged into the noise."""

    label: str
    opponents: tuple[tuple[str, str, Mapping[str, int]], ...]


@dataclass(frozen=True)
class BulkDeck:
    """`deck_id` must be unique: it names this deck's file in Forge's deck
    directory, and two decks sharing a name would race over one file."""

    deck_id: str
    commander: str
    counts: Mapping[str, int]


def connect(db_path: Path = DEFAULT_DB) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path, timeout=60)
    con.execute("""CREATE TABLE IF NOT EXISTS bulk_games (
        deck_id TEXT NOT NULL,
        table_label TEXT NOT NULL,
        seed INTEGER NOT NULL,
        commander TEXT NOT NULL,
        counts TEXT NOT NULL,
        games INTEGER NOT NULL,
        wins REAL NOT NULL,
        PRIMARY KEY (deck_id, table_label, seed))""")
    return con


def stored_pairs(con: sqlite3.Connection) -> set[tuple[str, str, int]]:
    return {(d, t, s) for d, t, s in
            con.execute("SELECT deck_id, table_label, seed FROM bulk_games")}


def run_bulk(decks: Sequence[BulkDeck], tables: Sequence[Table], *,
             games: int, seed: int, db_path: Path = DEFAULT_DB,
             max_workers: int = TOTAL_JVMS, clock_seconds: int = 420,
             evaluator_factory: Callable[..., object] | None = None,
             progress: Callable[[int, int], None] | None = None) -> int:
    """Play every deck against every table. Returns the number of games added.

    Each work item is one JVM running `games` games, which amortises startup
    over the batch while keeping the item small enough that a stall costs one
    slot. Items already in the database are skipped, so this is resumable and
    idempotent.
    """
    factory = evaluator_factory or (
        lambda opponents: ForgeSimEvaluator(opponents, workers=1,
                                            clock_seconds=clock_seconds))
    evaluators = {table.label: factory(list(table.opponents)) for table in tables}

    con = connect(db_path)
    try:
        done = stored_pairs(con)
    finally:
        con.close()

    work = [(deck, table) for table in tables for deck in decks
            if (deck.deck_id, table.label, seed) not in done]
    if not work:
        return 0

    added = 0
    finished = 0
    total = len(work)

    def play(item: tuple[BulkDeck, Table]) -> tuple[BulkDeck, Table, float, int]:
        deck, table = item
        result = evaluators[table.label].evaluate(
            deck.deck_id, deck.commander, deck.counts, n_games=games, seed=seed)
        return deck, table, sum(result.samples["win_rate"]), result.n_games

    from concurrent.futures import ThreadPoolExecutor, as_completed

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(play, item) for item in work]
        for future in as_completed(futures):
            finished += 1
            try:
                deck, table, wins, played = future.result()
            except Exception as exc:            # one bad pairing must not
                print(f"  pairing failed: {exc}", flush=True)   # kill the run
                continue
            with _WRITE_LOCK:
                con = connect(db_path)
                try:
                    con.execute(
                        "INSERT OR REPLACE INTO bulk_games VALUES (?,?,?,?,?,?,?)",
                        (deck.deck_id, table.label, seed, deck.commander,
                         json.dumps(dict(deck.counts)), played, wins))
                    con.commit()
                finally:
                    con.close()
            added += played
            if progress:
                progress(finished, total)
    return added


def training_rows(db_path: Path = DEFAULT_DB,
                  ) -> list[tuple[list[str], str, int, float]]:
    """Every stored pairing as (cards, table_label, games, wins).

    `cards` is the deck's distinct card names — the regression's features. Basic
    lands are dropped: the curve template pins their count, so they carry no
    contrast and would only add a column of constants.
    """
    basics = {"Forest", "Island", "Swamp", "Mountain", "Plains", "Wastes"}
    con = connect(db_path)
    try:
        rows = con.execute(
            "SELECT counts, table_label, games, wins FROM bulk_games").fetchall()
    finally:
        con.close()
    out = []
    for counts_json, label, games, wins in rows:
        cards = [name for name in json.loads(counts_json) if name not in basics]
        out.append((cards, label, int(games), float(wins)))
    return out


def summarise(rows: Iterable[tuple[list[str], str, int, float]]) -> str:
    rows = list(rows)
    games = sum(r[2] for r in rows)
    wins = sum(r[3] for r in rows)
    cards = {name for r in rows for name in r[0]}
    tables = {r[1] for r in rows}
    return (f"{len(rows)} pairings, {games} games, {len(cards)} distinct cards, "
            f"{len(tables)} tables, overall win rate "
            f"{wins / games if games else 0:.3f}")
