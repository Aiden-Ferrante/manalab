"""What a spell may point at, and enumerating the legal choices.

Targets arrive from the card parser as English: `"target creature"`, `"any
target"`, `"target creature you control"`. This module turns the phrases it
recognises into a `TargetSpec` and **refuses the rest**, which is the entire
design. A parser that guessed at `"target creature an opponent controls"` and
returned "any creature" would make removal spells legal in places the rules
forbid, and the resulting win rates would look completely reasonable.

The recognised set is small on purpose, and it is small because the distribution
is: across mono-coloured Modern instants and sorceries whose verbs the engine
implements, `no target`, `target creature`, `any target` and `target creature you
control` account for the overwhelming majority of target slots. The long tail is
357 distinct phrases, most appearing once.

Legality is checked at *resolution* as well as on announcement (CR 608.2b). A
spell whose only target left the battlefield in response does nothing — which
matters the moment two removal spells exist in the same game.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from manalab.engine.state import GameState
from manalab.engine.zones import Zone


class TargetKind(Enum):
    NONE = "none"
    """The effect takes no target: draw a card, gain life."""
    CREATURE = "creature"
    ANY = "any"
    """Creature or player. Magic's "any target" also includes planeswalkers,
    which this engine does not implement, so the phrase is honest here only
    because there are none on the battlefield to miss."""
    CREATURE_YOU_CONTROL = "creature_you_control"
    PLAYER = "player"
    OPPONENT = "opponent"

    SPELL = "spell"
    """An object on the stack. What a counterspell points at.

    Targets are chosen on announcement, while the counterspell is still in hand,
    so the stack it sees never contains the counterspell itself."""
    CREATURE_SPELL = "creature_spell"
    NONCREATURE_SPELL = "noncreature_spell"


    ALL_CREATURES = "all_creatures"
    """Every creature on the battlefield. A *scope*, not a target.

    "Destroy all creatures" does not target (CR 115.10) — there is no choice to
    make, nothing to be made illegal in response, and no hexproof to respect.
    Modelling it as a target would generate one castable option per creature for
    a spell that hits them all, which is both wrong and combinatorially silly."""


SPELL_KINDS = frozenset(
    {TargetKind.SPELL, TargetKind.CREATURE_SPELL, TargetKind.NONCREATURE_SPELL}
)

MASS_KINDS = frozenset({TargetKind.ALL_CREATURES})


@dataclass(frozen=True)
class TargetSpec:
    kind: TargetKind
    count: int = 1

    @property
    def needs_target(self) -> bool:
        """Whether the caster must choose something on announcement.

        Mass effects are excluded: they apply to everything in scope, so there is
        nothing to choose and nothing to enumerate.
        """
        return self.kind is not TargetKind.NONE and self.kind not in MASS_KINDS

    @property
    def is_mass(self) -> bool:
        return self.kind in MASS_KINDS


NO_TARGET = TargetSpec(TargetKind.NONE)

_PHRASES: dict[str, TargetKind] = {
    "any target": TargetKind.ANY,
    "target creature": TargetKind.CREATURE,
    "target creature you control": TargetKind.CREATURE_YOU_CONTROL,
    "target player": TargetKind.PLAYER,
    "target opponent": TargetKind.OPPONENT,
    "each opponent": TargetKind.OPPONENT,
    "you": TargetKind.PLAYER,
    # The counterspell family. The parser drops the leading "target" for these,
    # so the phrases arrive bare. "spell unless its controller pays {3}" is
    # deliberately absent: it needs a pay-or-not decision from the spell's
    # controller, which is a choice point the engine has nowhere to put yet.
    "spell": TargetKind.SPELL,
    "target spell": TargetKind.SPELL,
    "creature spell": TargetKind.CREATURE_SPELL,
    "target creature spell": TargetKind.CREATURE_SPELL,
    "noncreature spell": TargetKind.NONCREATURE_SPELL,
    "target noncreature spell": TargetKind.NONCREATURE_SPELL,
    # Board sweepers. "each other" and "all other" exclude the source, which for
    # an instant or sorcery is not a creature anyway — so they coincide here.
    # A permanent with that text is refused for its text regardless.
    "all creatures": TargetKind.ALL_CREATURES,
    "each creature": TargetKind.ALL_CREATURES,
    "all other creatures": TargetKind.ALL_CREATURES,
    "each other creature": TargetKind.ALL_CREATURES,
}

_ARTICLES = re.compile(r"^(a|an|the)\s+", re.I)


def parse(phrase: str | int | None) -> TargetSpec | None:
    """A spec for a phrase the engine can honour, or `None` to refuse it.

    Returning `None` rather than a best guess is the point. Every caller treats
    `None` as "this card is not modelled" and reports it by name.
    """
    if phrase is None:
        return NO_TARGET
    if not isinstance(phrase, str):
        return None

    cleaned = _ARTICLES.sub("", phrase.strip().lower()).rstrip(".")
    kind = _PHRASES.get(cleaned)
    return TargetSpec(kind) if kind is not None else None


# --- enumeration --------------------------------------------------------


@dataclass(frozen=True)
class Target:
    """A chosen target: either a permanent or a player.

    Kept as one type so an action can carry a heterogeneous choice ("any
    target") without the caller branching on which it got.
    """

    object_id: int | None = None
    player: int | None = None

    @property
    def is_player(self) -> bool:
        return self.player is not None

    def describe(self, state: GameState) -> str:
        if self.is_player:
            return f"P{self.player}"
        obj = state.objects.get(self.object_id)
        return obj.card.name if obj else f"<gone {self.object_id}>"


def legal_targets(state: GameState, controller: int, spec: TargetSpec) -> list[Target]:
    """Every target `controller` could legally choose for `spec`."""
    if spec.kind is TargetKind.NONE:
        return []

    creatures = [
        Target(object_id=obj.id)
        for obj in state.creatures()
        if obj.zone is Zone.BATTLEFIELD
    ]
    players = [Target(player=p.index) for p in state.players if not p.has_lost]

    if spec.kind in SPELL_KINDS:
        on_stack = state.zone(Zone.STACK)
        if spec.kind is TargetKind.CREATURE_SPELL:
            on_stack = [o for o in on_stack if o.card.is_creature]
        elif spec.kind is TargetKind.NONCREATURE_SPELL:
            on_stack = [o for o in on_stack if not o.card.is_creature]
        return [Target(object_id=obj.id) for obj in on_stack]

    if spec.kind is TargetKind.CREATURE:
        return creatures
    if spec.kind is TargetKind.CREATURE_YOU_CONTROL:
        return [
            Target(object_id=obj.id) for obj in state.creatures(controller)
            if obj.zone is Zone.BATTLEFIELD
        ]
    if spec.kind is TargetKind.ANY:
        return creatures + players
    if spec.kind is TargetKind.PLAYER:
        return players
    if spec.kind is TargetKind.OPPONENT:
        return [t for t in players if t.player != controller]
    return []


def still_legal(state: GameState, controller: int, spec: TargetSpec, target: Target) -> bool:
    """CR 608.2b — a target illegal on resolution is not affected.

    Checked again rather than trusted from announcement, because the board can
    change between the two. A spell all of whose targets became illegal does
    nothing at all.
    """
    if target.is_player:
        player = state.players[target.player]
        if player.has_lost:
            return False
        return spec.kind in (TargetKind.ANY, TargetKind.PLAYER, TargetKind.OPPONENT)

    obj = state.objects.get(target.object_id)
    if obj is None:
        return False

    if spec.kind in SPELL_KINDS:
        # CR 608.2b again, and the case that makes counter-wars work: a spell
        # that already resolved, or was itself countered, is no longer there.
        if obj.zone is not Zone.STACK:
            return False
        if spec.kind is TargetKind.CREATURE_SPELL:
            return obj.card.is_creature
        if spec.kind is TargetKind.NONCREATURE_SPELL:
            return not obj.card.is_creature
        return True

    if obj.zone is not Zone.BATTLEFIELD or not obj.is_creature:
        return False
    if spec.kind is TargetKind.CREATURE_YOU_CONTROL and obj.controller != controller:
        return False
    return spec.kind in (
        TargetKind.ANY,
        TargetKind.CREATURE,
        TargetKind.CREATURE_YOU_CONTROL,
    )
