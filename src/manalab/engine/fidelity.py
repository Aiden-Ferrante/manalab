"""What the engine actually represents, asked of a card before a game starts.

`GameResult.unmodeled` reports blind spots *after* the fact. This module answers
the same question *before*, which is what lets a search restrict itself to a
pool it can trust rather than optimising over cards whose text is silently
ignored.

The engine is the right home for this: it is the only thing that knows what it
implements, and putting the predicate anywhere else means a second list of
keywords that drifts out of step with the first.

Being honest here is load-bearing. A deck search told that Craterhoof Behemoth
is a plain 5/5 will confidently rank it below a 6/6, and the answer will look
perfectly reasonable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import manalab.engine.resolve as resolve
from manalab.cards.model import Card
from manalab.engine.mana import MULTI_MANA

COMBAT_KEYWORDS = frozenset(
    {
        "flying",
        "reach",
        "menace",
        "trample",
        "deathtouch",
        "first strike",
        "double strike",
        "lifelink",
        "vigilance",
        "haste",
        "defender",
    }
)
"""Keywords `engine.combat` and `engine.objects` genuinely implement.

Anything outside this set is printed on the card and ignored by the engine.
"""

_REMINDER = re.compile(r"\([^)]*\)")
_MANA_ABILITY = re.compile(r"^\{t\}: add \{[wubrgc]\}\.?$", re.I)


@dataclass(frozen=True)
class Fidelity:
    """How well the engine represents one card."""

    card_name: str
    reasons: tuple[str, ...] = ()

    @property
    def faithful(self) -> bool:
        """Nothing about this card is ignored or approximated."""
        return not self.reasons

    def __bool__(self) -> bool:  # pragma: no cover - convenience only
        return self.faithful


def _residual_text(card: Card) -> str:
    """Oracle text with reminder text and bare keyword lines removed.

    What is left is text the engine would have to *do* something about. A
    vanilla creature and a creature that only says "Flying" both reduce to the
    empty string, because the engine handles the second one completely.
    """
    text = _REMINDER.sub("", card.oracle_text or "")
    kept: list[str] = []

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if _MANA_ABILITY.match(line):
            continue  # a basic "{T}: Add {G}." is exactly what mana.py does
        # A keyword line is a comma/semicolon-separated list of known keywords.
        parts = [p.strip().lower() for p in re.split(r"[;,]", line) if p.strip()]
        if parts and all(p in COMBAT_KEYWORDS for p in parts):
            continue
        kept.append(line)

    return " ".join(kept).strip()


def assess(card: Card) -> Fidelity:
    """Everything the engine would get wrong about this card, by name."""
    reasons: list[str] = []

    if card.has_faces:
        # Checked first, and before anything reads `oracle_text` or `is_land`.
        # A faced card carries its text on the faces and leaves the top level
        # blank, so every text-based check below would read "vanilla"; and
        # `is_land` is true for a "Sorcery // Land" modal card, which sends it
        # down the lands branch. Both were silently admitting transforming and
        # modal cards to the faithful pool as textless 0-drops.
        return Fidelity(card.name, ("multi-faced; the engine plays only one side",))

    if card.is_land:
        # Lands are modelled as mana sources and nothing else.
        if _residual_text(card):
            reasons.append("land with text the engine ignores")
        if card.taps_for_mana and MULTI_MANA.search(card.oracle_text or ""):
            reasons.append("produces more than one mana; counted as one")
        elif not card.taps_for_mana:
            reasons.append("land that produces no mana the engine understands")
        return Fidelity(card.name, tuple(reasons))

    if not card.is_permanent:
        # Asked of `resolve`, never re-derived here. A second list of implemented
        # verbs is a second thing to forget to update, and the failure mode is a
        # card admitted to the faithful pool that the engine cannot execute.
        blocked = list(resolve.unsupported(card))
        # `resolve` can only judge the verbs that parsed. Text the parser never
        # matched produces no verb at all, so it was invisible here — the land
        # and creature branches both ask `_residual_text` and this one asked
        # nothing. That is how Pact of Negation entered the pool as a free,
        # drawback-free counterspell: "pay {3}{U}{U}, or you lose the game" was
        # dropped by the parser, so there was no verb for `resolve` to refuse.
        if card.unparsed:
            blocked.append("text the parser could not read")
        return Fidelity(card.name, tuple(blocked))

    if "Legendary" in card.type_line:
        # The engine has no legend rule (see `sba`), so a second copy on the
        # battlefield survives when the real game would bin it. That makes extra
        # copies strictly better here and strictly worse in Magic — a search will
        # happily play four of a legend it should play one of. Found exactly this
        # way: a GA run came back with three copies of a legendary 9/7.
        reasons.append("legendary; the engine has no legend rule, so copies stack")

    if not card.is_creature:
        reasons.append("non-creature permanent; sits on the battlefield inertly")

    if card.is_creature and card.base_power is None:
        reasons.append("characteristic-defining power/toughness (a '*')")

    unknown = {k.lower() for k in card.keywords} - COMBAT_KEYWORDS
    if unknown:
        reasons.append("unimplemented keywords: " + ", ".join(sorted(unknown)))

    if _residual_text(card):
        reasons.append("rules text the engine does not execute")

    return Fidelity(card.name, tuple(reasons))


def faithful(card: Card) -> bool:
    """Shorthand for `assess(card).faithful`."""
    return assess(card).faithful
