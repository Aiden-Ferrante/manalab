"""Draw the precision sample: parses for a human to mark, not for code to grade.

Recall is automatic — the coverage report counts it. Precision is not: an
error-free return can still misrepresent the card, and the two numbers must never
be merged. This dumps a random sample of *successful* parses side by side with
their oracle text, and deliberately seeds it with the kinds where parsers quietly
go wrong:

  an ability-word card · a modal spell with bullets · a planeswalker (loyalty uses
  U+2212 MINUS, not a hyphen) · a saga · a costed keyword with no colon · a keyword
  whose reminder text contains a colon · a multi-keyword line

    python -u examples/audit_effects.py [n]  ->  reports/audit_effects.md

The script does not attempt to self-assess correctness. Every row ends in an
unfilled verdict column; the marking is the point.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

from manalab.cards.effects import parse_card
from manalab.cards.store import CardStore

# One named example of each shape that historically breaks parsers. Names, not
# predicates, so the sample is reproducible and the kind is guaranteed present.
TRICKY = {
    "ability word": "Trapjaw Tyrant",
    "modal bullets": "Cryptic Command",
    "planeswalker U+2212": "Liliana of the Veil",
    "saga chapters": "History of Benalia",
    "costed keyword, no colon": "Batterskull",
    "reminder text with colon": "Sylvan Library",
    "four keywords, one line": "Akroma, Angel of Wrath",
    "quoted grant": "Sedge Sliver",
    "leveler": "Caravan Escort",
    "split faces": "Fire // Ice",
}


def block(card, parsed, kind: str | None) -> str:
    lines = [f"## {card.name}" + (f"  *(seeded: {kind})*" if kind else "")]
    lines.append("")
    lines.append(f"`{card.faces[0].type_line if card.faces else card.type_line}`"
                 f" · coverage {parsed.coverage:.0%}")
    lines.append("")
    lines.append("**Oracle text**")
    lines.append("")
    lines.append("```")
    for face in card.faces or ():
        if len(card.faces) > 1:
            lines.append(f"— {face.name} —")
        lines.append(face.oracle_text or "(no text)")
    lines.append("```")
    lines.append("")
    lines.append("**Parsed**")
    lines.append("")
    for ability in parsed.abilities:
        head = ability.kind
        if ability.cost:
            head += f" [{ability.cost}]"
        if ability.trigger:
            head += f" [{ability.trigger[:60]}]"
        for e in ability.effects:
            params = ", ".join(f"{k}={v!r}" for k, v in e.params)
            lines.append(f"- `{e.verb}({params})` — {head}")
        for u in ability.unparsed:
            lines.append(f"- ✗ unparsed: `{u[:90]}`")
    if not parsed.abilities:
        lines.append("- (no abilities)")
    lines.append("")
    lines.append("**Verdict** — [ ] faithful · [ ] wrong verb · [ ] wrong params"
                 " · [ ] missing meaning")
    lines.append("")
    return "\n".join(lines)


def main(n: int = 30) -> int:
    store = CardStore()
    out = Path("reports")
    out.mkdir(exist_ok=True)

    picked: list[tuple[object, str | None]] = []
    seen: set[str] = set()
    for kind, name in TRICKY.items():
        try:
            card = store.by_name(name)
        except Exception:
            continue
        picked.append((card, kind))
        seen.add(card.name)

    rng = random.Random(17)
    pool = [c for c in store.sample(400, seed=17)
            if c.name not in seen and parse_card(c).effects]
    rng.shuffle(pool)
    picked += [(c, None) for c in pool[: max(0, n - len(picked))]]

    body = [
        "# Effect-parse audit — unmarked",
        "",
        f"{len(picked)} cards: every tricky kind, then random successful parses.",
        "Mark each verdict; a row left unmarked is a row not audited. The",
        "sample answers *precision* — recall is the coverage report's job, and",
        "the two numbers must never be merged.",
        "",
    ]
    for card, kind in picked:
        body.append(block(card, parse_card(card), kind))

    dest = out / "audit_effects.md"
    dest.write_text("\n".join(body))
    print(f"wrote {dest} — {len(picked)} cards, verdicts unmarked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 30))
