"""A fixed set of opponents, built from cards the engine models faithfully.

A gauntlet is a claim about what a deck has to beat. Two properties matter more
than the individual lists:

  * **Spread.** Opponents that differ only in card choice all reward the same
    thing, and a search against them learns one strategy that happens to have
    five names. These archetypes differ on the axis the engine actually
    represents — how fast the board fills and how big it gets — so beating all
    of them requires more than a single curve.
  * **Fixedness.** The gauntlet must not change between generations. A moving
    target turns "fitness improved" into an uninterpretable statement, and
    co-evolving both sides is a much harder experiment wearing the same clothes.

Every deck here is assembled from the faithful tier, so a loss is never the
engine failing to read an opponent's card.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from manalab.cards.model import Card
from manalab.evaluate.match import GauntletDeck
from manalab.evaluate.pool import Pool

BASIC = {"Forest", "Mountain", "Island", "Plains", "Swamp"}


@dataclass(frozen=True)
class Archetype:
    """A recipe, not a decklist — so the same shapes can be built in any colour."""

    name: str
    lands: int
    score: Callable[[Card], float]
    """Higher is more wanted. Cards scoring below zero are never included."""

    max_cmc: int = 99

    spell_slots: int = 0
    """How many of the non-land slots go to instants and sorceries.

    Zero for the creature archetypes, which is what every archetype used to be —
    and the reason a search could never learn that removal exists. A gauntlet of
    decks that only attack grades every candidate on the same axis, so a burn
    deck and a do-nothing deck are indistinguishable to it.

    Capped rather than unbounded on purpose: a deck of 36 burn spells and no
    creatures wins 0.008 of its games, because it takes eight damage a turn while
    dealing two and a half. Spells want a board to defend, not to replace one.
    """

    spell_score: Callable[[Card], float] | None = None
    """Ranks the spells. `None` means this archetype takes no spells."""


def _creatures(pool: Pool) -> list[Card]:
    """Creatures a gauntlet deck can actually field.

    Zero-toughness creatures are excluded: they die to state-based actions the
    moment they resolve, because the counter or the anthem that makes them
    legal is text the engine does not execute. Left in, the aggro recipe happily
    drafts four copies of an 8/0 flier and hands the search a free win it would
    then be tuned against. They stay in the *candidate* pool, where a search is
    entitled to discover for itself that they are unplayable.
    """
    return [
        card
        for card in pool.cards.values()
        if card.is_creature
        and card.name not in BASIC
        and card.base_power is not None
        and (card.base_toughness or 0) >= 1
    ]


def _stats(card: Card) -> tuple[int, int, float]:
    return card.base_power or 0, card.base_toughness or 0, card.cmc


def _spells(pool: Pool) -> list[Card]:
    """Instants and sorceries the engine can actually resolve."""
    return [
        card
        for card in pool.cards.values()
        if not card.is_permanent and not card.is_land
    ]


def _fill(candidates: list[Card], score, slots: int, copies: int) -> list[Card]:
    """Take the best-scoring cards, `copies` apiece, until `slots` runs out."""
    wanted = [c for c in candidates if score(c) >= 0]
    # Name breaks ties so the gauntlet is byte-identical across runs and machines.
    wanted.sort(key=lambda c: (-score(c), c.name))

    chosen: list[Card] = []
    for card in wanted:
        if slots <= 0:
            break
        take = min(copies, slots)
        chosen.extend([card] * take)
        slots -= take
    return chosen


def build(pool: Pool, archetype: Archetype, *, copies: int = 4) -> GauntletDeck:
    """Fill a 60-card deck: basics, then spells if the recipe wants any, then creatures.

    A recipe that asks for spells a colour does not have degrades into a creature
    deck rather than failing — blue has almost no damage, so a burn recipe there
    is a creature deck wearing the name. That is honest degradation, but it does
    mean a colour's gauntlet is only as diverse as its pool allows.
    """
    basic = next(c for c in pool.cards.values() if c.name in BASIC)
    cards: list[Card] = [basic] * archetype.lands
    slots = 60 - archetype.lands

    if archetype.spell_slots and archetype.spell_score is not None:
        spells = _fill(
            [c for c in _spells(pool) if c.cmc <= archetype.max_cmc],
            archetype.spell_score,
            min(archetype.spell_slots, slots),
            copies,
        )
        cards.extend(spells)
        slots -= len(spells)

    creatures = _fill(
        [c for c in _creatures(pool) if c.cmc <= archetype.max_cmc],
        archetype.score,
        slots,
        copies,
    )
    cards.extend(creatures)
    slots -= len(creatures)

    if slots > 0:  # pragma: no cover - only if the pool is tiny
        cards.extend([basic] * slots)

    return GauntletDeck(name=archetype.name, cards=tuple(cards))


ARCHETYPES: tuple[Archetype, ...] = (
    Archetype(
        "aggro",
        lands=20,
        max_cmc=3,
        # Power per mana, with a floor on the body so it is not all 1/1s.
        score=lambda c: _stats(c)[0] / max(1.0, c.cmc) + 0.25 * _stats(c)[0],
    ),
    Archetype(
        "midrange",
        lands=24,
        max_cmc=5,
        score=lambda c: (_stats(c)[0] + _stats(c)[1]) / max(1.0, c.cmc),
    ),
    Archetype(
        "fatties",
        lands=26,
        # Raw size, so it is slow but nearly unblockable in a fair fight.
        score=lambda c: _stats(c)[0] + _stats(c)[1] + 2.0 * c.cmc,
    ),
    Archetype(
        "defensive",
        lands=24,
        # Toughness first: walls the aggro decks cannot get through.
        score=lambda c: 2.0 * _stats(c)[1] - _stats(c)[0] / 2.0,
    ),
    Archetype(
        "evasion",
        lands=22,
        max_cmc=5,
        # Only creatures the engine's blockers struggle with actually count.
        score=lambda c: (
            _stats(c)[0] * (2.0 if (c.has("Flying") or c.has("Trample")) else 0.0)
            + (3.0 if c.has("Deathtouch") else 0.0)
            + (3.0 if (c.has("First strike") or c.has("Double strike")) else 0.0)
            - 1.0
        ),
    ),
)


def _verbs(card: Card) -> set[str]:
    return {effect.verb for effect in card.effects}


def _is_sweeper(card: Card) -> bool:
    """Destroys or damages every creature at once, and the engine can run it."""
    import manalab.engine.targets as _targets

    for effect in card.effects:
        if effect.verb not in ("destroy", "deal_damage"):
            continue
        spec = _targets.parse(effect.get("target"))
        if spec is not None and spec.is_mass:
            return True
    return False


def _damage_amount(card: Card) -> float:
    return max(
        (float(e.get("amount", 0)) for e in card.effects
         if e.verb == "deal_damage" and isinstance(e.get("amount"), int)),
        default=0.0,
    )


def _reaches_face(card: Card) -> bool:
    """Whether the damage can go at the player, not only at a creature."""
    return any(
        e.verb == "deal_damage" and str(e.get("target", "")).lower() == "any target"
        for e in card.effects
    )


SPELL_ARCHETYPES: tuple[Archetype, ...] = (
    Archetype(
        "burn",
        lands=20,
        max_cmc=4,
        spell_slots=16,
        # Damage per mana, with a bonus for being able to aim at the player —
        # a deck that can only hit creatures cannot close a game.
        spell_score=lambda c: (
            _damage_amount(c) / max(1.0, c.cmc) + (1.0 if _reaches_face(c) else -0.5)
            if "deal_damage" in _verbs(c) else -1.0
        ),
        score=lambda c: _stats(c)[0] / max(1.0, c.cmc),
    ),
    Archetype(
        "removal",
        lands=23,
        spell_slots=14,
        # Answers first: counter it, destroy it, or burn it off the board.
        # Countering is rated alongside destroying rather than above it — it is
        # the more efficient answer in principle, but only for a player who kept
        # mana up, and the crude pilot taps out every turn.
        spell_score=lambda c: (
            # A sweeper answers a whole board, so it is rated above a one-for-one.
            6.0 if _is_sweeper(c)
            else 3.0 if "counter_spell" in _verbs(c)
            else 3.0 if "destroy" in _verbs(c)
            else _damage_amount(c) - 1.0 if "deal_damage" in _verbs(c)
            else 1.0 if "draw" in _verbs(c)
            else -1.0
        ),
        score=lambda c: (_stats(c)[0] + _stats(c)[1]) / max(1.0, c.cmc),
    ),
)
"""Decks that answer things, rather than only attacking.

Added after a five-colour tournament ranked red last with a champion holding
zero damage spells. Its gauntlet was creature-only, so a deck that could not be
punished for having no removal beat one that had it — red had learned the
correct answer to the wrong question.
"""

FULL: tuple[Archetype, ...] = ARCHETYPES + SPELL_ARCHETYPES


def standard(pool: Pool, archetypes: Sequence[Archetype] = FULL) -> tuple[GauntletDeck, ...]:
    """The default gauntlet: one deck per archetype."""
    return tuple(build(pool, a) for a in archetypes)


def describe(pool: Pool, archetypes: Sequence[Archetype] = FULL) -> list[tuple[str, int, int, int]]:
    """`(name, lands, creatures, spells)` per deck — for checking a gauntlet is diverse."""
    out = []
    for archetype in archetypes:
        deck = build(pool, archetype)
        lands = sum(1 for c in deck.cards if c.is_land)
        spells = sum(1 for c in deck.cards if not c.is_permanent and not c.is_land)
        out.append((archetype.name, lands, len(deck.cards) - lands - spells, spells))
    return out
