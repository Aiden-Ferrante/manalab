"""The abstract simulator: one player, no opponent, no interaction.

WHAT IT MODELS
  - Shuffling, London mulligans, the draw step, one land drop per turn
  - Correct colored-mana payment via bipartite matching (see game.mana)
  - Lands that enter tapped
  - Mana rocks and dorks that tap for exactly one mana, with summoning sickness
  - A greedy curve-out policy: each turn, cast the most expensive castable
    spell, repeat until nothing is castable

WHAT IT DOES NOT MODEL
  - An opponent. There is no combat, no removal, no interaction, no winning.
  - Card draw, tutors, scry, surveil, fetchlands, cost reduction
  - Anything that produces more than one mana from a single source
  - Alternate and additional costs, X spells

The second list is why `GameRecord.unmodeled` exists. Cards whose text implies
behaviour the sim ignores are reported by name on every run, so a result is
never quietly built on a deck the model can't represent. Read that field before
believing any number this produces.

Because of the above, valid questions are about *consistency and clock*:
"how often can this deck cast its three-drop on turn three", not "does this deck
win". Optimizing a proxy you can defend beats optimizing a win rate you can't.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from manalab.cards.model import Card
from manalab.game.library import shuffle
from manalab.game.mana import Source, assign
from manalab.game.mulligan import BottomPolicy, KeepPolicy, mulligan

DEFAULT_TURNS = 8


@dataclass(frozen=True)
class GameRecord:
    """The complete observable result of one simulated game."""

    mulligans: int
    opening_hand: tuple[str, ...]
    mana_available: tuple[int, ...]
    """Untapped sources during the main phase of each turn, 1-indexed as [0]=turn 1."""
    lands_in_play: tuple[int, ...]
    missed_land_drops: int
    spells_cast: tuple[int, ...]
    cast_turn: Mapping[str, int]
    """Card name -> earliest turn it was actually cast. Policy-dependent: with
    one mana and two one-drops in hand, only one of them gets cast."""
    castable_turn: Mapping[str, int]
    """Card name -> earliest turn it was in hand *and* payable from untapped
    sources, whether or not the policy chose to cast it.

    This is the mana-base question ("can this deck support a turn-3 {B}{B}?")
    and it is the one `--target` reports. Measuring casts instead would conflate
    the mana base with the play policy's arbitrary tie-breaks."""
    total_mana_spent: int

    def on_curve_through(self, turn: int) -> bool:
        """Did every turn up to `turn` have at least that much mana available?"""
        if turn > len(self.mana_available):
            return False
        return all(self.mana_available[t - 1] >= t for t in range(1, turn + 1))

    def cast_by(self, card_name: str, turn: int) -> bool:
        return self.cast_turn.get(card_name, 10**6) <= turn

    def castable_by(self, card_name: str, turn: int) -> bool:
        return self.castable_turn.get(card_name, 10**6) <= turn


@dataclass
class _Permanent:
    card: Card
    available_from: int


def play(
    library: Sequence[Card],
    *,
    seed: int,
    turns: int = DEFAULT_TURNS,
    on_the_play: bool = True,
    keep: KeepPolicy | None = None,
    bottom: BottomPolicy | None = None,
) -> GameRecord:
    """Simulate one goldfish game. Pure in `(library, seed, policies)`.

    Purity is the point: comparing two decks on identical seeds is the variance
    reduction that makes search affordable.
    """
    rng = random.Random(seed)
    deck = shuffle(library, rng)
    hand, rest, mulls = mulligan(deck, rng, keep=keep, bottom=bottom)
    opening = tuple(c.name for c in hand)

    battlefield: list[_Permanent] = []
    mana_by_turn: list[int] = []
    lands_by_turn: list[int] = []
    casts_by_turn: list[int] = []
    cast_turn: dict[str, int] = {}
    castable_turn: dict[str, int] = {}
    missed_drops = 0
    mana_spent = 0

    for turn in range(1, turns + 1):
        if not (turn == 1 and on_the_play):
            if rest:
                hand.append(rest.pop(0))

        # --- land drop ---------------------------------------------------
        land_idx = _choose_land(hand, _sources(battlefield, turn))
        if land_idx is None:
            if len(_lands(battlefield)) < turn:
                missed_drops += 1
        else:
            land = hand.pop(land_idx)
            battlefield.append(
                _Permanent(land, available_from=turn + 1 if land.enters_tapped else turn)
            )

        # --- main phase --------------------------------------------------
        sources = _sources(battlefield, turn)
        available = len(sources)
        casts = 0

        # Castability is measured against the full untapped board, before any
        # spell is cast, so it reflects the mana base rather than the order the
        # play policy happened to spend mana in.
        for card in hand:
            if not card.is_land and card.name not in castable_turn:
                if assign(card.cost, sources) is not None:
                    castable_turn[card.name] = turn

        while True:
            choice = _best_castable(hand, sources)
            if choice is None:
                break
            idx, used = choice
            card = hand.pop(idx)
            cast_turn.setdefault(card.name, turn)
            mana_spent += len(used)
            casts += 1

            spent = set(used)
            sources = [s for i, s in enumerate(sources) if i not in spent]

            # Rocks and dorks join the battlefield and pay for things later.
            if card.taps_for_mana:
                battlefield.append(
                    _Permanent(card, available_from=turn + 1 if card.is_creature else turn)
                )
                if not card.is_creature:
                    sources.append(card.produces)

        mana_by_turn.append(available)
        lands_by_turn.append(len(_lands(battlefield)))
        casts_by_turn.append(casts)

    return GameRecord(
        mulligans=mulls,
        opening_hand=opening,
        mana_available=tuple(mana_by_turn),
        lands_in_play=tuple(lands_by_turn),
        missed_land_drops=missed_drops,
        spells_cast=tuple(casts_by_turn),
        cast_turn=cast_turn,
        castable_turn=castable_turn,
        total_mana_spent=mana_spent,
    )


def _lands(battlefield: Sequence[_Permanent]) -> list[_Permanent]:
    return [p for p in battlefield if p.card.is_land]


def _sources(battlefield: Sequence[_Permanent], turn: int) -> list[Source]:
    return [
        p.card.produces
        for p in battlefield
        if p.card.taps_for_mana and p.available_from <= turn
    ]


def _choose_land(hand: Sequence[Card], sources: Sequence[Source]) -> int | None:
    """Pick which land to play, given what is already on the battlefield.

    Ordering by hand position (or even by "untapped first") is not good enough:
    holding a Mountain, a Plains and a {R} one-drop, a naive rule plays the
    Plains half the time and the deck looks two colored sources worse than it
    is. Every multicolor mana-base number depends on getting this right.

    The rule, in priority order:
      1. enable the most expensive spell castable this turn
      2. then enable the most spells
      3. then prefer a land that enters tapped — if it costs nothing right now,
         playing it now is strictly better than playing it later
      4. then prefer more colors

    A real player also sequences around future turns and knows what's left in
    the deck. This doesn't. It is a stated policy, not an optimal one.
    """
    lands = [i for i, c in enumerate(hand) if c.is_land]
    if not lands:
        return None

    spells = [c for c in hand if not c.is_land]
    base = list(sources)
    scored: dict[tuple[frozenset[str], bool, bool], tuple[int, int]] = {}

    def score(i: int) -> tuple[int, int, bool, int]:
        land = hand[i]
        key = (land.produces, land.enters_tapped, land.taps_for_mana)
        if key not in scored:
            # A land entering tapped contributes nothing until next turn.
            usable = base + ([] if land.enters_tapped or not land.taps_for_mana
                             else [land.produces])
            best_cmc, count = -1, 0
            for spell in spells:
                if assign(spell.cost, usable) is not None:
                    count += 1
                    best_cmc = max(best_cmc, spell.cmc)
            scored[key] = (best_cmc, count)
        best_cmc, count = scored[key]
        return (best_cmc, count, land.enters_tapped, len(land.produces))

    return max(lands, key=score)


def _best_castable(
    hand: Sequence[Card], sources: Sequence[Source]
) -> tuple[int, tuple[int, ...]] | None:
    """Most expensive castable spell, and the sources that pay for it.

    Greedy by mana value. This is a stated policy, not an optimal one: it will
    happily cast a four-drop over two two-drops. Swapping in a better policy is
    a local change to this function.
    """
    best: tuple[int, tuple[int, ...]] | None = None
    best_cmc = -1
    for i, card in enumerate(hand):
        if card.is_land or card.cmc <= best_cmc:
            continue
        used = assign(card.cost, sources)
        if used is not None:
            best, best_cmc = (i, used), card.cmc
    return best


# --- honesty layer -------------------------------------------------------

_UNMODELED = (
    ("card draw", re.compile(r"\bdraws? (a|two|three|\d+) cards?", re.I)),
    ("tutor", re.compile(r"search your library", re.I)),
    ("scry/surveil", re.compile(r"\b(scry|surveil)\b", re.I)),
    ("multi-mana source", re.compile(r"add (\{[^}]+\})\s*\{", re.I)),
    ("cost reduction", re.compile(r"costs? \{[^}]+\} less", re.I)),
    ("alternative cost", re.compile(r"(without paying its mana cost|you may cast)", re.I)),
)

_FETCHLAND_NOTE = "fetchland, approximated as an untapped dual"


def scan_unmodeled(cards: Sequence[Card]) -> dict[str, list[str]]:
    """Card name -> behaviours the sim ignores or approximates.

    Call this before trusting a result. A deck with eight cantrips and four
    tutors will simulate as a much worse deck than it is.

    Approximations are reported alongside outright blind spots, on purpose:
    "we modeled this, roughly" and "we ignored this" are both things you need to
    know before quoting a number, and hiding the first is how a simulator starts
    lying quietly.
    """
    out: dict[str, list[str]] = {}
    for card in cards:
        reasons: list[str] = []
        is_fetch = card.is_land and card.taps_for_mana and "search your library" in card.oracle_text.lower()

        for label, rx in _UNMODELED:
            if not rx.search(card.oracle_text):
                continue
            # A fetchland's "search your library" is approximated, not ignored.
            reasons.append(_FETCHLAND_NOTE if (label == "tutor" and is_fetch) else label)

        if card.cost.approximated:
            reasons.append("approximated mana cost")
        if reasons:
            out[card.name] = reasons
    return out
