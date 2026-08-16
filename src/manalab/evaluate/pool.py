"""Assembling a card pool the engine can be trusted on.

Lives in `evaluate` rather than `cards` for a reason worth stating: deciding
which cards are safe to search over needs *both* the card data and the engine's
account of its own blind spots. `cards` may not import `engine`, so a pool
builder there would need a hand-copied list of implemented keywords — a second
source of truth that silently drifts the first time a keyword is added.

The split this produces is the honest one:

  * **faithful** — every word on the card is executed. Search over these and the
    resulting win rate means what it says.
  * **text** — the card is playable as a body, but some of its text is ignored.
    Kept and labelled rather than dropped, so it is visible what the engine is
    throwing away, and which verbs would unlock the most cards if implemented.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Iterable, Mapping

from manalab.cards import forge_import, formats
from manalab.cards.formats import Format
from manalab.cards.model import Card, CandidatePool
from manalab.cards.store import CardStore
from manalab.engine import fidelity


@dataclass(frozen=True)
class Pool:
    """A searchable pool plus everything that was set aside, and why."""

    pool: CandidatePool
    cards: Mapping[str, Card]
    """Name -> Card for every card in `pool`, ready to hand to an evaluator."""

    text_tier: tuple[Card, ...] = ()
    """Playable, but with text the engine ignores. Not in `pool`."""

    reasons: Mapping[str, tuple[str, ...]] = None  # type: ignore[assignment]
    """Why each text-tier card was set aside."""

    def __post_init__(self) -> None:
        if self.reasons is None:
            object.__setattr__(self, "reasons", {})

    @property
    def size(self) -> int:
        return len(self.pool.card_ids)

    def why(self, card_name: str) -> tuple[str, ...]:
        return tuple(self.reasons.get(card_name, ()))

    def gaps(self) -> list[tuple[str, int]]:
        """Reasons for exclusion, commonest first — the implement-next list."""
        counts: dict[str, int] = {}
        for reasons in self.reasons.values():
            for reason in reasons:
                key = reason.split(":")[0]
                counts[key] = counts.get(key, 0) + 1
        return sorted(counts.items(), key=lambda kv: kv[1], reverse=True)


def best_effects(card: Card, oracle) -> Card:
    """Our parse, falling back to Forge's encoding when ours cannot play the card.

    Lives here rather than in `cards` for the same reason the pool builder does:
    deciding which encoding to keep needs the engine's account of itself, and
    `cards` may not import `engine`. The layer test caught this being written in
    the wrong package.

    The two sources overlap rather than nest — on mono-green Commander the
    English parser makes 540 cards playable and the Forge import 294, and the
    union is 578. Taking the union is the whole gain.

    **Which to prefer was decided by measurement, and the obvious answer was
    wrong.** Forge's encodings are correctness-pressured, so "prefer Forge
    wherever it translates completely" looked right. It scores **468** — worse
    than the parser alone: it takes Forge's answer on 795 cards, disagrees on 406
    of them, and loses 72 playable cards net. A complete *translation* is not a
    complete *card*.

    So the rule is conservative: keep what already works, reach for Forge only
    where we have nothing. Monotone by construction — it can never score below
    the parser alone. On the green pool it fires on 38 cards.

    Accuracy is a separate job with its own instrument: where both work and
    disagree, `examples/forge_validation.py` reports it (31 cards today). That is
    a work list for the parser, not a reason to swap encodings wholesale.
    """
    if not fidelity.assess(card).reasons:
        return card
    imported = forge_import.with_forge_effects(card, oracle)
    if imported is card or fidelity.assess(imported).reasons:
        return card
    return imported


def mono_color(
    store: CardStore,
    color: str = "G",
    *,
    fmt: Format | str = formats.MODERN,
    max_cmc: int = 7,
    include_lands: bool = True,
    deck_size: int | None = None,
) -> Pool:
    """Every single-colour card of `color` that is legal in `fmt`.

    Colourless cards are excluded deliberately: they are legal in a mono-green
    deck but they are not a *green* deckbuilding decision, and letting them in
    turns "what is the best mono-green deck" into "what is the best colourless
    deck with a forest in it".

    `fmt` takes a `Format` or its name; the format supplies the deck size and the
    copy limits, so a Commander pool comes out singleton at 100 without the
    caller restating either. `deck_size` still overrides, for the experiments
    that vary it deliberately.

    Restricted cards are *included* and capped at one. Filtering on `= 'legal'`
    excluded them entirely, which silently emptied Vintage of the fifty-two
    cards that define it.
    """
    fmt = formats.by_name(fmt) if isinstance(fmt, str) else fmt
    identity = json.dumps([color])
    rows = store._rows(  # noqa: SLF001 - the store exposes no typed filter yet
        """
        color_identity = ?
        AND json_extract_string(CAST(legalities AS JSON), '$.' || ?)
            IN ('legal', 'restricted')
        AND cmc <= ?
        """,
        [identity, fmt.legality_key, max_cmc],
    )
    candidates = [store._build(row) for row in rows]  # noqa: SLF001

    if include_lands:
        basic = store.by_name({"G": "Forest", "R": "Mountain", "U": "Island",
                               "W": "Plains", "B": "Swamp"}[color])
        candidates.append(basic)

    return partition(candidates, fmt=fmt, legal=store.legality_in(fmt.legality_key),
                     deck_size=deck_size)


def partition(
    candidates: Iterable[Card],
    *,
    deck_size: int | None = None,
    unlimited: Iterable[str] = (),
    fmt: Format | None = None,
    legal: Mapping[str, str] | None = None,
) -> Pool:
    """Split cards into the faithful pool and the marked text tier.

    With a `fmt` the construction rules come from the format — deck size, copy
    limit, singleton, which cards are exempt — and `legal` supplies each card's
    status so restricted cards land at one copy. Without one the old defaults
    apply, which is what the hand-built fixtures want.
    """
    if fmt is not None:
        deck_size = fmt.deck_size if deck_size is None else deck_size
        unlimited = fmt.unlimited if not unlimited else unlimited
    deck_size = 60 if deck_size is None else deck_size
    unlimited = set(unlimited)
    faithful: list[Card] = []
    text: list[Card] = []
    reasons: dict[str, tuple[str, ...]] = {}

    for card in sorted(set(candidates), key=lambda c: (c.cmc, c.name)):
        report = fidelity.assess(card)
        if report.faithful:
            faithful.append(card)
        else:
            text.append(card)
            reasons[card.name] = report.reasons

    names = tuple(c.name for c in faithful)
    if fmt is not None:
        pool = fmt.candidate_pool(names, legal or {})
        if deck_size != fmt.deck_size:      # an explicit override wins
            pool = replace(pool, deck_size=deck_size)
    else:
        # A basic land is capped by the deck size, not by the four-copy rule.
        pool = CandidatePool(
            card_ids=names,
            max_copies={c.name: deck_size for c in faithful if c.name in unlimited},
            deck_size=deck_size,
        )
    return Pool(
        pool=pool,
        cards={c.name: c for c in faithful},
        text_tier=tuple(text),
        reasons=reasons,
    )
