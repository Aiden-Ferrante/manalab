"""Forge's rules engine as an evaluator: full Magic, every card, four seats.

This is the swap ADR 0002's seam existed for. The internal engine executes a
measured fraction of the game (381 faithful mono-green cards, 27% of a real
precon) and refuses the rest honestly; Forge executes practically all of it —
33,617 cards, the complete rules — through its headless `sim` mode, seeded and
local. The trade, stated plainly:

  * **Fidelity**: complete. A precon plays as printed; no fidelity caveat.
  * **Pilot**: Forge's AI, which its own wiki calls untrained heuristics. The
    number still means "wins this table under this pilot" — ADR 0001's reason
    for refusing this as an *objective* stands. It is an execution engine here.
  * **Cost**: ~10-15s per game plus JVM startup, against the internal engine's
    0.1s. Batch per process (`-n`), and spend games accordingly.
  * **CRN**: `-S` seeds a whole N-game run reproducibly, but game *i* is not
    addressable at seed *s+i*, so the Oracle's splicing contract does NOT hold.
    Fine for evaluation and held-out measurement; a search loop that assumes
    splicing must not use this evaluator yet.

Requires a Forge install and a JDK; `available()` reports honestly instead of
failing mid-campaign.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import threading
from pathlib import Path
from typing import Callable, Mapping, Sequence

from manalab.evaluate.result import EvalResult

FORGE_JAR = Path.home() / ".local/forge/forge-gui-desktop-2.0.14-jar-with-dependencies.jar"
JAVA = next(iter(sorted(Path.home().glob(".local/jdk-*/bin/java"))), Path("java"))
FORGE_DECKS = Path.home() / ".forge/decks/commander"

_GAME_RESULT = re.compile(r"Game Result: Game \d+ ended in \d+ ms\. (.+?) has won")
_DRAW = re.compile(r"Game Result: .*draw", re.I)

PARSE_VERSION = 2
"""Bumped when the meaning of a parsed result changes, and part of the cache
key so a stored result computed by an older, wronger parser is never reused.

v2: clock-capped games are draws, not wins. Forge expresses a timed-out game
by logging EVERY player as "has won because all opponents have lost", then
naming one of them on the single `Game Result` line. v1 read that line and
credited the named player. Measured at a 25s clock: of 9 capped games, 8 were
named for seat Ai(2) and 1 for Ai(1) — so a draw was a phantom win for one
opponent roughly nine times in ten, while the candidate always sits in seat 1.
At the production 420s clock, 2 of 8 games capped, which is enough of the
sample to matter. Draws are now excluded from the win rate and reported
separately."""


def parse_results(stdout: str, candidate: str) -> list[float | None]:
    """One entry per game: 1.0 candidate won, 0.0 lost, None the game drew.

    A game's outcome block starts at `Game Outcome: Turn` and lists one line
    per player. Exactly one "has won" is a real result; more than one means
    nobody actually won and the game hit the clock.
    """
    results: list[float | None] = []
    winners_in_block = 0
    for line in stdout.splitlines():
        if "Game Outcome: Turn" in line:
            winners_in_block = 0
            continue
        if "Game Outcome" in line and "has won" in line:
            winners_in_block += 1
            continue
        found = _GAME_RESULT.search(line)
        if found:
            results.append(None if winners_in_block > 1
                           else (1.0 if candidate in found.group(1) else 0.0))
            winners_in_block = 0
        elif _DRAW.search(line):
            results.append(None)
            winners_in_block = 0
    return results

TOTAL_JVMS = 14
_SLOTS = threading.BoundedSemaphore(TOTAL_JVMS)
"""One global budget for concurrent Forge processes, whatever spawns them.

Per-evaluation `workers` used to be the only cap, so an 8-game evaluation
filled 8 slots and left the rest of a 20-core box idle while evaluations
queued. Campaigns may now run several evaluations concurrently (a plain
ThreadPoolExecutor over `evaluate` calls) and this semaphore keeps the
machine at its budget instead of over- or under-subscribed."""

_JSA = Path.home() / ".local/forge/forge-appcds.jsa"
_CACHE_DB = Path("data/forge_cache.sqlite")
_CACHE_LOCK = threading.Lock()


def _cache() -> sqlite3.Connection:
    _CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(_CACHE_DB)
    con.execute("""CREATE TABLE IF NOT EXISTS results (
        key TEXT PRIMARY KEY, samples TEXT NOT NULL)""")
    return con


def _cache_key(candidate_counts, commander, opponents, seed, games, clock) -> str:
    payload = json.dumps([sorted(candidate_counts.items()), commander,
                          [(n, g, sorted(c.items())) for n, g, c in opponents],
                          seed, games, clock, PARSE_VERSION])
    return hashlib.sha256(payload.encode()).hexdigest()


def available() -> bool:
    return FORGE_JAR.exists() and Path(JAVA).exists()


def write_dck(name: str, commander: str, counts: Mapping[str, int],
              directory: Path) -> Path:
    """One deck in Forge's .dck format. The commander is its own section."""
    lines = ["[metadata]", f"Name={name}", "[Commander]", f"1 {commander}", "[Main]"]
    for card_name, count in sorted(counts.items()):
        if card_name == commander:
            count -= 1
        if count > 0:
            lines.append(f"{count} {card_name}")
    # Atomic: the bulk runner has many threads writing decks while other JVMs
    # read them, and a torn read of a half-written deck file is a corrupt game
    # that looks like a rules result.
    path = directory / f"{name}.dck"
    tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text("\n".join(lines) + "\n")
    os.replace(tmp, path)
    return path


def _result(deck_name: str, evaluator: str, played: Sequence[float | None],
            seed: int) -> EvalResult:
    """Win rate over DECIDED games; draws reported, never scored as losses.

    Scoring a draw 0 would punish the candidate for a game nobody won, and
    scoring it as a win credits whichever seat Forge happened to name. Both
    are wrong; excluding it and reporting the rate separately is not."""
    decided = [w for w in played if w is not None]
    draws = len(played) - len(decided)
    return EvalResult(
        deck_name=deck_name, evaluator=evaluator,
        n_games=len(decided), seed=seed,
        metrics={"win_rate": sum(decided) / len(decided) if decided else 0.0,
                 "draw_rate": draws / len(played) if played else 0.0,
                 "games_played": float(len(played))},
        samples={"win_rate": tuple(decided)},
    )


class ForgeSimEvaluator:
    """Win share of seat 0's deck at a four-seat table, under the full rules."""

    def __init__(self, opponents: Sequence[tuple[str, str, Mapping[str, int]]],
                 *, clock_seconds: int = 900, workers: int = 1) -> None:
        """`opponents`: three (name, commander, counts) triples.

        `workers` runs that many seeded JVMs at once. A game is single-threaded
        Java, so a 20-core box playing one game at a time idles 90% of itself;
        chunking the batch across processes is where the Spark's compute
        actually goes (its GPU has no role here — a rules engine does not
        tensorise, the same measured verdict as the internal engine's).

        Reproducibility survives with a caveat: chunk *i* runs at seed
        `seed + 1000*i`, so results are identical across runs AT THE SAME
        WORKER COUNT, but a serial run and a parallel run play different games.
        The worker count is part of the experiment and belongs in its record.
        """
        if len(opponents) != 3:
            raise ValueError("a Commander table wants exactly three opponents")
        self.opponents = list(opponents)
        self.clock_seconds = clock_seconds
        self.workers = max(1, workers)
        self.evaluator = "forge-sim"

    def evaluate(self, deck_name: str, commander: str, counts: Mapping[str, int],
                 *, n_games: int, seed: int,
                 futility: "Callable[[int, int, int], bool] | None" = None) -> EvalResult:
        """`futility(wins, played, remaining)` -> True stops buying games.

        The evaluation then returns the games actually played — fewer than
        asked, honestly reported in `n_games`. Sound only when the stopping
        rule is fixed before the run (a pre-registered cut in a halving round);
        peeking-and-stopping on a whim is the garden of forking paths.
        """
        if not available():
            raise RuntimeError(f"Forge not found at {FORGE_JAR}")
        key = _cache_key(dict(counts), commander, self.opponents, seed,
                         n_games, self.clock_seconds)
        with _CACHE_LOCK, _cache() as con:
            row = con.execute("SELECT samples FROM results WHERE key=?",
                              (key,)).fetchone()
        if row:
            return _result(deck_name, self.evaluator, json.loads(row[0]), seed)
        FORGE_DECKS.mkdir(parents=True, exist_ok=True)

        candidate = f"cand_{deck_name}"[:40].replace(" ", "_")
        names = [candidate]
        write_dck(candidate, commander, counts, FORGE_DECKS)
        for i, (name, general, opp_counts) in enumerate(self.opponents):
            safe = f"opp{i}_{name}"[:40].replace(" ", "_")
            names.append(safe)
            write_dck(safe, general, opp_counts, FORGE_DECKS)

        def run_chunk(chunk_seed: int, games: int) -> list[float | None]:
            cmd = [str(JAVA), "-Xmx3g",
                   # AppCDS: cache the class-loading half of JVM startup across
                   # runs. First run writes the archive, later runs boot faster.
                   f"-XX:SharedArchiveFile={_JSA}", "-XX:+AutoCreateSharedArchive",
                   "-jar", str(FORGE_JAR), "sim",
                   "-d", *[f"{n}.dck" for n in names],
                   "-f", "Commander", "-n", str(games), "-S", str(chunk_seed),
                   "-c", str(self.clock_seconds), "-q"]
            with _SLOTS:
                proc = subprocess.run(cmd, capture_output=True, text=True,
                                      cwd=FORGE_JAR.parent,
                                      timeout=games * self.clock_seconds + 300)
            chunk_wins = parse_results(proc.stdout, candidate)
            if len(chunk_wins) != games:
                raise RuntimeError(
                    f"expected {games} results at seed {chunk_seed}, parsed "
                    f"{len(chunk_wins)} — tail: {proc.stdout[-400:]!r}")
            return chunk_wins

        workers = min(self.workers, n_games)
        base, extra = divmod(n_games, workers)
        chunks = [(seed + 1000 * i, base + (1 if i < extra else 0))
                  for i in range(workers) if base + (1 if i < extra else 0) > 0]
        wins: list[float | None] = []
        if len(chunks) == 1:
            wins = run_chunk(*chunks[0])
        elif futility is None:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=len(chunks)) as pool_:
                wins = [w for chunk in pool_.map(lambda c: run_chunk(*c), chunks)
                        for w in chunk]
        else:
            # Two waves: buy half, consult the stopping rule, buy the rest.
            from concurrent.futures import ThreadPoolExecutor
            half = max(1, len(chunks) // 2)
            for wave in (chunks[:half], chunks[half:]):
                if not wave:
                    continue
                with ThreadPoolExecutor(max_workers=len(wave)) as pool_:
                    wins.extend(w for chunk in pool_.map(
                        lambda c: run_chunk(*c), wave) for w in chunk)
                remaining = n_games - len(wins)
                decided_now = [w for w in wins if w is not None]
                if remaining and futility(int(sum(decided_now)),
                                          len(decided_now), remaining):
                    break

        with _CACHE_LOCK, _cache() as con:
            con.execute("INSERT OR REPLACE INTO results VALUES (?, ?)",
                        (key, json.dumps(wins)))
        return _result(deck_name, self.evaluator, wins, seed)
