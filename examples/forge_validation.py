"""Validate our card parse against Forge's hand-encoded card scripts.

Every check this project had until now was internal: unit tests we wrote against
boards we built, and a coverage number computed by the same parser it grades.
Karsten's tables are the one external check, and they only cover the mana base —
they say nothing about what a spell does when it resolves. That is exactly where
the 2026-08-15 audit found the engine executing cards wrongly.

Forge closes that gap. It publishes ~33,700 cards as verb plus named parameters,
maintained by people who run them in a real rules engine, and the encoding is
close enough to `Effect(verb, params)` to diff directly. This script does that
diff and reports where we disagree.

    python examples/forge_validation.py            # needs data/forge (see below)
    python -c "from manalab.cards import forge; forge.fetch()"

It is a *comparison*, not an import. We do not adopt Forge's ontology and we do
not ship its data; the scripts live in gitignored `data/` like the Scryfall
corpus. See ADR 0008.

Read the disagreement classes rather than the total. A card we refuse outright is
not a bug — refusing is the honest outcome. What matters is the third and fourth
sections: cards we call FAITHFUL, and therefore execute, where Forge says the
card does something we never encoded.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from manalab.cards import forge
from manalab.cards.store import CardStore
from manalab.engine import fidelity
from manalab.engine.resolve import _pump_amount

# Our verb -> the Forge verb that means the same thing. Deliberately confined to
# the six the engine can actually resolve: a disagreement about a verb nobody
# executes is a parser curiosity, while a disagreement about these is a wrong
# game. `Counter` covers the counterspell family; `Destroy` excludes `DestroyAll`
# because a one-sided removal spell and a wrath are not the same card.
VERB_MAP = {
    "deal_damage": "DealDamage",
    "destroy": "Destroy",
    "draw": "Draw",
    "gain_life": "GainLife",
    "pump": "Pump",
    "counter_spell": "Counter",
}
FORGE_TO_OURS = {v: k for k, v in VERB_MAP.items()}


def _num(raw: str | None) -> int | None:
    """Forge writes `+3`, `-3`, `0` or a variable like `X`. None means variable."""
    try:
        return int(str(raw or 0).lstrip('+'))
    except ValueError:
        return None


def main() -> int:
    cards_dir = forge.default_dir()
    if not cards_dir.exists():
        print(f"no Forge scripts at {cards_dir}", file=sys.stderr)
        print("fetch them first:  python -c \"from manalab.cards import forge; forge.fetch()\"",
              file=sys.stderr)
        return 2

    oracle = forge.load(cards_dir)
    store = CardStore()
    cards = list(store.all_cards())

    matched = 0
    dropped: list[tuple[str, str]] = []       # we execute it, Forge has a verb we lack
    asymmetric: list[tuple[str, str]] = []    # pump whose two halves differ
    lost_target: list[tuple[str, str]] = []   # Forge targets a player, we do not
    divided: list[str] = []                   # damage split across targets
    verb_gaps: Counter[str] = Counter()

    for card in cards:
        ref = oracle.get(forge.slug(card.name))
        if ref is None:
            continue
        matched += 1

        faithful = not fidelity.assess(card).reasons
        ours = Counter(e.verb for e in (card.effects or ()))
        chain = ref.effect_chain()
        theirs = Counter(a.verb for a in chain)

        # (1) a verb Forge encodes, mapped into our vocabulary, that we never produced
        for fverb, n in theirs.items():
            ours_verb = FORGE_TO_OURS.get(fverb)
            if ours_verb is None:
                continue
            have = ours.get(ours_verb, 0)
            if fverb == "Pump":
                # Forge writes "gains lifelink until end of turn" as Pump with a
                # KW$ parameter; we write it as grant_ability. Same card, two
                # spellings — counting only our pump flagged correct cards.
                have += ours.get("grant_ability", 0)
            if have < n:
                verb_gaps[fverb] += 1
                if faithful:
                    dropped.append((card.name, f"{fverb} x{n} vs our {ours.get(ours_verb, 0)}"))

        # (2) pump amounts, compared value by value against Forge's two fields.
        #
        # This deliberately does NOT flag asymmetry as such. It used to, back when
        # the engine collapsed both halves with `max(power, toughness)` — but once
        # that was fixed the check kept reporting 38 correctly-executed cards as
        # defects. A validator that cannot tell a fixed bug from a live one is
        # worse than no validator, so it now asks the only question that matters:
        # do we execute the numbers the card is printed with?
        for ability in chain:
            if ability.verb != "Pump" or not faithful:
                continue
            theirs_pt = (_num(ability.get("NumAtt")), _num(ability.get("NumDef")))
            if None in theirs_pt:
                break          # Forge says X — a variable we do not model either way
            ours_pt = next((_pump_amount(dict(e.params))
                            for e in (card.effects or ()) if e.verb == "pump"), None)
            if ours_pt is not None and tuple(ours_pt) != theirs_pt:
                asymmetric.append(
                    (card.name, f"we {ours_pt[0]:+}/{ours_pt[1]:+} vs printed "
                                f"{theirs_pt[0]:+}/{theirs_pt[1]:+}"))
            break

        # (3) Forge aims at a player; our effect carries no target, so the caster gets it
        for ability in chain:
            if ability.verb not in ("Draw", "GainLife"):
                continue
            if "Player" not in (ability.get("ValidTgts") or ""):
                continue
            ours_verb = FORGE_TO_OURS[ability.verb]
            has_target = any(e.verb == ours_verb and e.get("target")
                             for e in (card.effects or ()))
            if faithful and not has_target and ours_verb in ours:
                lost_target.append((card.name, f"{ability.verb} -> {ability.get('ValidTgts')}"))
            break

        # (4) damage divided among targets — one number on our side, several on theirs
        if faithful and any(a.get("DividedAsYouChoose") for a in chain):
            divided.append(card.name)

    _report(len(cards), matched, dropped, asymmetric, lost_target, divided, verb_gaps)
    return 1 if (dropped or asymmetric or lost_target or divided) else 0


def _show(rows, limit: int = 8) -> str:
    head = "; ".join(f"{n} ({d})" if d else n for n, d in rows[:limit])
    return head + (f"  ... +{len(rows) - limit} more" if len(rows) > limit else "")


def _report(total, matched, dropped, asymmetric, lost_target, divided, verb_gaps) -> None:
    print()
    print("  FORGE ORACLE — where our parse disagrees with a hand-encoded corpus")
    print("  " + "=" * 70)
    print(f"  corpus                  : {total:,} cards")
    print(f"  matched a Forge script  : {matched:,} ({100 * matched / total:.1f}%)")
    print()
    print("  Disagreements on cards we call FAITHFUL — these are executed, so each")
    print("  one is a game played wrongly, not a parser curiosity.")
    print("  " + "-" * 70)
    print(f"  [1] effect we never encoded   : {len(dropped):>5}   {_show(dropped)}")
    print(f"  [2] pump amount mismatch      : {len(asymmetric):>5}   {_show(asymmetric)}")
    print(f"  [3] target player dropped     : {len(lost_target):>5}   {_show(lost_target)}")
    print(f"  [4] divided damage flattened  : {len(divided):>5}   "
          f"{_show([(n, '') for n in divided])}")
    print()
    if verb_gaps:
        print("  Corpus-wide verb gaps (faithful or not), most common first:")
        for verb, n in verb_gaps.most_common(8):
            print(f"     {verb:<14} {n:>6} cards where Forge has one and we do not")
    print()


if __name__ == "__main__":
    sys.exit(main())
