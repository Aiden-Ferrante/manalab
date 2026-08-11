"""Objects in a game: a card plus everything true of it right now.

`Card` (in `manalab.cards`) is frozen and shared — every copy of Lightning Bolt
in every deck is the same object. `GameObject` is the mutable per-instance state
the engine tracks: where it is, who controls it, whether it is tapped, what has
been done to it.

Keeping those apart is what allows 35,000 cards to be loaded once and a game to
be cheap to clone.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Mapping

from manalab.cards.model import Card
from manalab.engine.zones import Zone


@dataclass
class GameObject:
    id: int
    card: Card
    owner: int
    """Who started the game with it. Never changes."""
    controller: int
    """Who currently controls it. Changes with theft effects; resets on zone change."""
    zone: Zone

    tapped: bool = False
    damage: int = 0
    counters: dict[str, int] = field(default_factory=dict)
    summoning_sick: bool = False
    """Set when a permanent enters the battlefield, cleared during its
    controller's untap step. A creature with this cannot attack or pay {T},
    unless it has haste."""
    attached_to: int | None = None
    face_down: bool = False

    attacking: int | None = None
    """Player being attacked, while this creature is an attacker."""
    blocking: int | None = None
    """Id of the attacker this creature is blocking."""
    blocked_by: tuple[int, ...] = ()
    """Blockers assigned to this attacker. An attacker that is blocked and then
    loses all its blockers stays blocked and deals no damage (CR 509.1h), which
    is why this is not recomputed from `blocking`."""

    # --- characteristics ------------------------------------------------
    # Read through these rather than through `.card`, so that continuous
    # effects (anthems, layers) have one place to hook in later.

    @property
    def name(self) -> str:
        return self.card.name

    @property
    def types(self) -> str:
        return self.card.type_line

    @property
    def is_creature(self) -> bool:
        return self.card.is_creature

    @property
    def is_land(self) -> bool:
        return self.card.is_land

    @property
    def power(self) -> int:
        base = self.card.base_power
        return (base or 0) + self.counters.get("+1/+1", 0) - self.counters.get("-1/-1", 0)

    @property
    def toughness(self) -> int:
        base = self.card.base_toughness
        return (base or 0) + self.counters.get("+1/+1", 0) - self.counters.get("-1/-1", 0)

    @property
    def lethal_damage(self) -> bool:
        """Toughness 0 or less, or damage marked at least equal to toughness.

        Only meaningful for creatures on the battlefield; the caller checks that.
        """
        return self.toughness <= 0 or self.damage >= self.toughness

    def has(self, keyword: str) -> bool:
        return self.card.has(keyword)

    @property
    def can_tap(self) -> bool:
        """Untapped, and not held back by summoning sickness.

        Sickness only restrains creatures — an artifact that entered this turn
        can tap for mana immediately, which is why Sol Ring is Sol Ring.
        """
        if self.tapped:
            return False
        if self.is_creature and self.summoning_sick and not self.has("Haste"):
            return False
        return True

    @property
    def can_attack(self) -> bool:
        return (
            self.is_creature
            and not self.tapped
            and (not self.summoning_sick or self.has("Haste"))
            and not self.has("Defender")
        )

    def add_counters(self, kind: str, n: int = 1) -> None:
        self.counters[kind] = self.counters.get(kind, 0) + n
        if self.counters[kind] <= 0:
            self.counters.pop(kind, None)

    def fresh_copy(self, new_id: int, zone: Zone, controller: int) -> "GameObject":
        """The new object this card becomes on changing zones (CR 400.7).

        Deliberately drops damage, counters, tapped status and attachments. If
        you ever find yourself wanting to carry one of those across a zone
        change, the rules almost certainly disagree.
        """
        return GameObject(
            id=new_id,
            card=self.card,
            owner=self.owner,
            controller=controller,
            zone=zone,
        )

    @property
    def is_blocked(self) -> bool:
        return bool(self.blocked_by)

    def leave_combat(self) -> None:
        self.attacking = None
        self.blocking = None
        self.blocked_by = ()

    def clone(self) -> "GameObject":
        return replace(self, counters=dict(self.counters))

    def __repr__(self) -> str:
        marks = []
        if self.tapped:
            marks.append("tapped")
        if self.summoning_sick:
            marks.append("sick")
        if self.damage:
            marks.append(f"dmg{self.damage}")
        if self.counters:
            marks.extend(f"{k}x{v}" for k, v in sorted(self.counters.items()))
        suffix = f" [{' '.join(marks)}]" if marks else ""
        return f"<{self.id} {self.card.name} @{self.zone}{suffix}>"
