"""How much of Magic does the effect parser actually understand?

Run after changing anything in `manalab.cards.effects`:

    python -u examples/effect_coverage.py

Reports coverage over the whole 35k-card corpus and lists the largest remaining
gaps, grouped by clause shape so that "deals 3 damage" and "deals 5 damage"
count as one gap rather than many. The gap list is the work queue: it is ordered
by how many cards each missing pattern would unlock.

Coverage is not a score to maximise. A card below 1.0 is a card the engine must
not pretend to understand, and the point of measuring is to know which ones
those are.
"""

from __future__ import annotations

from manalab.cards import effects
from manalab.cards.store import CardStore

TOP_GAPS = 30


def main() -> None:
    # parse_effects=False: `measure` parses for itself, and letting the store do
    # it too would double the work for an identical result.
    with CardStore(parse_effects=False) as store:
        cards = store.all_cards()

    report = effects.measure(cards)

    print(f"corpus            {report.cards:,} cards")
    print(f"  no oracle text  {report.vanilla:,}")
    print(f"  fully parsed    {report.fully_parsed:,}  ({report.card_rate:.1%})")
    print(f"  clauses matched {report.matched:,}/{report.clauses:,}  ({report.clause_rate:.1%})")

    print(f"\n{'verb':<24}{'occurrences':>12}")
    for verb, count in report.top_verbs(20):
        print(f"  {verb:<22}{count:>12,}")

    print(f"\nlargest remaining gaps ({TOP_GAPS} of {len(report.misses):,} distinct shapes)")
    for clause, count in report.top_misses(TOP_GAPS):
        print(f"  {count:>6,}  {clause}")

    tail = sum(report.misses.values()) - sum(c for _, c in report.top_misses(TOP_GAPS))
    print(f"\n  {tail:,} further unparsed clauses across the long tail.")


if __name__ == "__main__":
    main()
