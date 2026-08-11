"""Command line entry point. `python -m manalab --help`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DATA = Path("data")
DB = DATA / "cards.duckdb"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="manalab", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="download Scryfall bulk card data")
    p_fetch.add_argument("--kind", default="oracle_cards")
    p_fetch.add_argument("--force", action="store_true")
    p_fetch.add_argument("--dry-run", action="store_true", help="show size, download nothing")

    p_build = sub.add_parser("build", help="load downloaded card data into DuckDB")
    p_build.add_argument("--kind", default="oracle_cards")
    sub.add_parser("info", help="show card store status")

    p_sim = sub.add_parser("sim", help="run the consistency evaluator on a decklist")
    p_sim.add_argument("decklist", type=Path)
    p_sim.add_argument("-n", "--games", type=int, default=10_000)
    p_sim.add_argument("--seed", type=int, default=0)
    p_sim.add_argument("--draw", action="store_true", help="simulate on the draw")
    p_sim.add_argument(
        "--target",
        action="append",
        default=[],
        metavar="CARD:TURN",
        help='e.g. --target "Wrath of God:4" (repeatable)',
    )

    args = parser.parse_args(argv)
    return _DISPATCH[args.command](args)


def _cmd_fetch(args: argparse.Namespace) -> int:
    from manalab.cards import bulk

    index = bulk.fetch_index()
    entry = index.get(args.kind)
    if entry is None:
        print(f"unknown kind {args.kind!r}; available: {', '.join(sorted(index))}")
        return 1

    dest = DATA / f"{args.kind}{entry.suffix}"
    print(f"{entry.kind}: {entry.size_mb:.1f} MB compressed, updated {entry.updated_at}")
    print(f"  {entry.download_uri}\n  -> {dest}")
    if args.dry_run:
        return 0

    before = dest.stat().st_mtime if dest.exists() else None
    bulk.download(args.kind, DATA, force=args.force)
    # Say which of the two things actually happened. "done" covered both keeping a
    # three-day-old file and downloading a fresh one, which is how staleness hid.
    if before is not None and dest.stat().st_mtime == before:
        print(f"already current ({dest.stat().st_size / 1_000_000:.1f} MB, "
              f"updated {entry.updated_at})")
    else:
        print(f"downloaded ({dest.stat().st_size / 1_000_000:.1f} MB)")
    return 0


def _cmd_build(args: argparse.Namespace) -> int:
    from manalab.cards import bulk, store

    src = bulk.path_for(args.kind, DATA)
    count = store.build(src, DB)
    print(f"built {DB} with {count:,} cards from {src}")
    return 0


def _cmd_info(_: argparse.Namespace) -> int:
    from manalab.cards.store import CardStore

    if not DB.exists():
        print(f"no card store at {DB} — run `manalab fetch` then `manalab build`")
        return 1
    with CardStore(DB) as cs:
        print(f"{DB}: {cs.count():,} cards")
    return 0


def _cmd_sim(args: argparse.Namespace) -> int:
    from manalab.cards import decklist as dl
    from manalab.cards.store import CardStore
    from manalab.evaluate.consistency import ConsistencyEvaluator

    deck = dl.load(args.decklist)

    targets = []
    for raw in args.target:
        name, _, turn = raw.rpartition(":")
        if not name or not turn.isdigit():
            print(f"bad --target {raw!r}; expected 'Card Name:TURN'")
            return 1
        targets.append((name, int(turn)))

    with CardStore(DB) as cs:
        cards = cs.resolve(deck.counts)

    evaluator = ConsistencyEvaluator(
        cards=cards, targets=targets, on_the_play=not args.draw
    )
    result = evaluator.evaluate(deck, n_games=args.games, seed=args.seed)

    print(f"{deck.name}  ({deck.size} cards, {args.games:,} games, seed {args.seed})")
    print(f"evaluator: {result.evaluator}\n")

    for key in sorted(result.metrics):
        lo, hi = result.ci95(key)
        print(f"  {key:<28} {result.metrics[key]:>8.4f}   [{lo:.4f}, {hi:.4f}]")

    if result.unmodeled:
        print(f"\n  !! {len(result.unmodeled)} card(s) the simulator cannot represent:")
        for name, reasons in sorted(result.unmodeled.items()):
            print(f"     {name}: {', '.join(reasons)}")
        print("     Treat these numbers as a lower bound on the deck's real consistency.")

    return 0


_DISPATCH = {
    "fetch": _cmd_fetch,
    "build": _cmd_build,
    "info": _cmd_info,
    "sim": _cmd_sim,
}


if __name__ == "__main__":
    sys.exit(main())
