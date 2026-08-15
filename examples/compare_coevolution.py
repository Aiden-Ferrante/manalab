"""Diff two co-evolution runs: what did implementing effect verbs change?

    python examples/compare_coevolution.py \\
        reports/archive/2026-08-15-pre-engine-fixes/coevo-before-verbs.txt \\
        reports/archive/2026-08-15-pre-engine-fixes/coevo-after-verbs.txt

Both inputs are archived: they were produced by an engine with three confirmed
execution defects (see reports/README.md). The structural observations they
support may survive; the magnitudes will not.

Reads the reports rather than re-running anything, so the comparison is over the
runs that actually happened. The two runs must share every parameter except the
engine — same seed, rounds, budget and matrix size — or this is comparing two
different experiments and saying something about verbs.

What to look at, in order of how much it means:

  colours in the equilibrium   one colour at weight ~1.0 is a degenerate
                               metagame. More colours sharing weight is the
                               thing removal is supposed to buy.
  cycles                       intransitivity is what makes a metagame a
                               metagame. A ladder has none.
  regressions                  how often optimising against the current field
                               made a deck worse against the previous one.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROUND = re.compile(r"^ROUND (\d+)")
MIXTURE = re.compile(r"^\s+([WUBRG]\d+)\s+([\d.]+)\s")
CYCLES = re.compile(r"^\s+intransitive triples \((\d+)\)")
NO_CYCLES = re.compile(r"no cycles")
PROGRESS = re.compile(r"^\s+([WUBRG]\d+)\s+([\d.]+)\s+(improved|held|REGRESSED)")

COLOR_OF = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}


def parse(path: Path) -> list[dict]:
    rounds: list[dict] = []
    current: dict | None = None
    section = ""

    for line in path.read_text(encoding="utf-8").splitlines():
        if (m := ROUND.match(line.strip())):
            current = {"round": int(m.group(1)), "mixture": {}, "progress": {},
                       "cycles": 0}
            rounds.append(current)
            section = ""
            continue
        if current is None:
            continue

        if "progress vs" in line:
            section = "progress"
            continue
        if "Nash mixture" in line:
            section = "mixture"
            continue
        if NO_CYCLES.search(line):
            current["cycles"] = 0
            section = ""
            continue
        if (m := CYCLES.match(line)):
            current["cycles"] = int(m.group(1))
            section = ""
            continue

        if section == "progress" and (m := PROGRESS.match(line)):
            current["progress"][m.group(1)] = (float(m.group(2)), m.group(3))
        elif section == "mixture" and (m := MIXTURE.match(line)):
            current["mixture"][m.group(1)] = float(m.group(2))

    return rounds


def summarise(name: str, rounds: list[dict]) -> dict:
    final = rounds[-1]
    colours = {COLOR_OF[label[0]] for label, w in final["mixture"].items() if w > 0.01}
    regressions = sum(1 for r in rounds for _, (_, verdict) in r["progress"].items()
                      if verdict == "REGRESSED")
    total = sum(len(r["progress"]) for r in rounds)
    return {
        "name": name,
        "rounds": len(rounds),
        "colours": colours,
        "mixture": final["mixture"],
        "cycles": [r["cycles"] for r in rounds],
        "regressions": regressions,
        "measured": total,
        "top": max(final["mixture"].values()) if final["mixture"] else 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    args = parser.parse_args()

    runs = []
    for label, path in (("before verbs", args.before), ("after verbs", args.after)):
        if not path.exists():
            print(f"missing: {path}")
            return 1
        rounds = parse(path)
        if not rounds:
            print(f"no rounds parsed from {path} — did the run finish?")
            return 1
        runs.append(summarise(label, rounds))

    print("=" * 74)
    print("WHAT IMPLEMENTING EFFECT VERBS CHANGED")
    print("=" * 74)
    print(f"{'':<26}{'before verbs':>22}{'after verbs':>22}")

    def row(label, a, b):
        print(f"{label:<26}{str(a):>22}{str(b):>22}")

    b, a = runs
    row("rounds", b["rounds"], a["rounds"])
    row("colours in equilibrium", len(b["colours"]), len(a["colours"]))
    row("", ", ".join(sorted(b["colours"])), ", ".join(sorted(a["colours"])))
    row("top deck's Nash weight", f"{b['top']:.3f}", f"{a['top']:.3f}")
    row("cycles per round", "->".join(map(str, b["cycles"])),
        "->".join(map(str, a["cycles"])))
    row("regressions", f"{b['regressions']}/{b['measured']}",
        f"{a['regressions']}/{a['measured']}")

    print("\nfinal Nash mixtures:")
    for run in runs:
        entries = sorted(run["mixture"].items(), key=lambda kv: -kv[1])
        shown = "  ".join(f"{k}={v:.3f}" for k, v in entries if v > 0.01)
        print(f"  {run['name']:<14} {shown}")

    print()
    if a["top"] < b["top"] - 0.05:
        print("The equilibrium got less degenerate: no single deck dominates as hard.")
    elif a["top"] > b["top"] + 0.05:
        print("The equilibrium got MORE degenerate. Worth asking which verb did it —")
        print("cheap removal can concentrate a metagame as easily as it opens one.")
    else:
        print("The equilibrium's concentration barely moved.")

    if len(a["colours"]) > len(b["colours"]):
        print("More colours survive, which is what removal and card draw are for.")
    elif len(a["colours"]) < len(b["colours"]):
        print("Fewer colours survive — the verbs helped one colour more than the rest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
