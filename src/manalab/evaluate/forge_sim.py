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
                 *, clock_seconds: int = 900) -> None:
        """`opponents`: three (name, commander, counts) triples."""
        if len(opponents) != 3:
            raise ValueError("a Commander table wants exactly three opponents")
        self.opponents = list(opponents)
        self.clock_seconds = clock_seconds
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

        cmd = [str(JAVA), "-Xmx4g", "-jar", str(FORGE_JAR), "sim",
               "-d", *[f"{n}.dck" for n in names],
               "-f", "Commander", "-n", str(n_games), "-S", str(seed),
               "-c", str(self.clock_seconds)]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              cwd=FORGE_JAR.parent,
                              timeout=n_games * self.clock_seconds + 300)

        wins: list[float] = []
        for line in proc.stdout.splitlines():
            found = _GAME_RESULT.search(line)
            if found:
                wins.append(1.0 if candidate in found.group(1) else 0.0)
            elif _DRAW.search(line):
                wins.append(0.0)
        if len(wins) != n_games:
            raise RuntimeError(
                f"expected {n_games} game results, parsed {len(wins)} — "
                f"tail of output: {proc.stdout[-500:]!r}")

        return EvalResult(
            deck_name=deck_name, evaluator=self.evaluator,
            n_games=n_games, seed=seed,
            metrics={"win_rate": sum(wins) / n_games},
            samples={"win_rate": tuple(wins)},
        )
