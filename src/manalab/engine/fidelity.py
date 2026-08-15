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
import manalab.engine.statics as statics
import manalab.engine.triggers as triggers
from manalab.cards.model import Card
from manalab.engine.mana import MULTI_MANA

from manalab.engine.objects import COMBAT_KEYWORDS  # noqa: F401 - re-exported
"""Re-exported: callers have imported it from here since before it moved."""

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


def _residual_text(card: Card, skip: frozenset[str] = frozenset()) -> str:
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
        if line.strip().lower() in skip:
            continue        # a triggered ability the engine executes in full
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

    # Legendary permanents used to be refused here, because without the legend
    # rule a second copy survived and extra copies were strictly better in the
    # engine and strictly worse in Magic. `sba` now enforces 704.5j, so they are
    # admitted — which is what makes commanders expressible at all, since every
    # commander is legendary.

    if not card.is_creature:
        reasons.append("non-creature permanent; sits on the battlefield inertly")

    if card.is_creature and card.base_power is None:
        reasons.append("characteristic-defining power/toughness (a '*')")

    unknown = {k.lower() for k in card.keywords} - COMBAT_KEYWORDS
    if unknown:
        reasons.append("unimplemented keywords: " + ", ".join(sorted(unknown)))

    # A trigger the engine can honour is no longer "text it does not execute".
    # Anything it cannot recognise is still refused by name, which is what keeps
    # a half-understood trigger out of a search pool.
    reasons.extend(triggers.unsupported(card))
    reasons.extend(statics.unsupported(card))

    if _residual_text(card, skip=_handled_lines(card)):
        reasons.append("rules text the engine does not execute")

    return Fidelity(card.name, tuple(reasons))


def _handled_lines(card: Card) -> frozenset[str]:
    """Printed lines that are triggered abilities this engine fully executes.

    "Fully" is strict on purpose. The ability must parse completely, every verb
    must be one `resolve` implements, and none of its effects may need a target —
    a triggered ability has no announcement step here yet, so there is nowhere for
    a target to be chosen. Loosening any of those admits a card whose trigger
    fires and quietly does the wrong thing, which is the failure this whole layer
    exists to prevent.
    """
    handled: set[str] = set()
    for ability in card.abilities:
        # A static ability whose whole effect `statics` applies is executed, not
        # ignored — the same bar the triggered branch below uses.
        if ability.kind == "static" and ability.effects and not ability.unparsed \
                and statics.applicable(card) and not statics.unsupported(card) \
                and ability.text:
            handled.add(ability.text.strip().lower())
    for _, ability in triggers.watched_by(card):
        if ability.unparsed or not ability.effects:
            continue
        if any(e.verb not in resolve.IMPLEMENTED for e in ability.effects):
            continue
        if any(e.get("target") for e in ability.effects):
            continue
        if ability.text:
            handled.add(ability.text.strip().lower())
    return frozenset(handled)


def faithful(card: Card) -> bool:
    """Shorthand for `assess(card).faithful`."""
    return assess(card).faithful
