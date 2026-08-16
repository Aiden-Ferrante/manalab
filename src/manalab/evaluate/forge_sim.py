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

import re
import subprocess
import tempfile
from pathlib import Path
from typing import Mapping, Sequence

from manalab.evaluate.result import EvalResult

FORGE_JAR = Path.home() / ".local/forge/forge-gui-desktop-2.0.14-jar-with-dependencies.jar"
JAVA = next(iter(sorted(Path.home().glob(".local/jdk-*/bin/java"))), Path("java"))
FORGE_DECKS = Path.home() / ".forge/decks/commander"

_GAME_RESULT = re.compile(r"Game Result: Game \d+ ended in \d+ ms\. (.+?) has won")
_DRAW = re.compile(r"Game Result: .*draw", re.I)


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
    path = directory / f"{name}.dck"
    path.write_text("\n".join(lines) + "\n")
    return path


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
                 *, n_games: int, seed: int) -> EvalResult:
        if not available():
            raise RuntimeError(f"Forge not found at {FORGE_JAR}")
        FORGE_DECKS.mkdir(parents=True, exist_ok=True)

        candidate = f"cand_{deck_name}"[:40].replace(" ", "_")
        names = [candidate]
        write_dck(candidate, commander, counts, FORGE_DECKS)
        for i, (name, general, opp_counts) in enumerate(self.opponents):
            safe = f"opp{i}_{name}"[:40].replace(" ", "_")
            names.append(safe)
            write_dck(safe, general, opp_counts, FORGE_DECKS)

        def run_chunk(chunk_seed: int, games: int) -> list[float]:
            cmd = [str(JAVA), "-Xmx3g", "-jar", str(FORGE_JAR), "sim",
                   "-d", *[f"{n}.dck" for n in names],
                   "-f", "Commander", "-n", str(games), "-S", str(chunk_seed),
                   "-c", str(self.clock_seconds), "-q"]
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  cwd=FORGE_JAR.parent,
                                  timeout=games * self.clock_seconds + 300)
            chunk_wins: list[float] = []
            for line in proc.stdout.splitlines():
                found = _GAME_RESULT.search(line)
                if found:
                    chunk_wins.append(1.0 if candidate in found.group(1) else 0.0)
                elif _DRAW.search(line):
                    chunk_wins.append(0.0)
            if len(chunk_wins) != games:
                raise RuntimeError(
                    f"expected {games} results at seed {chunk_seed}, parsed "
                    f"{len(chunk_wins)} — tail: {proc.stdout[-400:]!r}")
            return chunk_wins

        workers = min(self.workers, n_games)
        base, extra = divmod(n_games, workers)
        chunks = [(seed + 1000 * i, base + (1 if i < extra else 0))
                  for i in range(workers) if base + (1 if i < extra else 0) > 0]
        if len(chunks) == 1:
            wins = run_chunk(*chunks[0])
        else:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=len(chunks)) as pool_:
                wins = [w for chunk in pool_.map(lambda c: run_chunk(*c), chunks)
                        for w in chunk]

        return EvalResult(
            deck_name=deck_name, evaluator=self.evaluator,
            n_games=n_games, seed=seed,
            metrics={"win_rate": sum(wins) / n_games},
            samples={"win_rate": tuple(wins)},
        )
