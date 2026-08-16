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

from manalab.cards.model import Ability, Card

COMBAT_KEYWORDS = frozenset({
    "flying", "reach", "menace", "trample", "deathtouch", "first strike",
    "double strike", "lifelink", "vigilance", "haste", "defender",
})
"""Keywords `engine.combat` and this module genuinely implement.

Lives here rather than in `fidelity` because `has()` is what answers for them,
and because `resolve` needs the same set to decide what it may grant — and
`fidelity` imports `resolve`, so the constant cannot live downstream of it
without a cycle or a second copy that drifts.
"""

TIMING_KEYWORDS = frozenset({"flash"})
"""Keywords implemented outside combat. Flash is read by `actions.legal`, which
offers a creature at instant speed when it has one.

Kept apart from COMBAT_KEYWORDS rather than folded in, because a test asserts
every entry in that set is read by `combat` or `objects` — and flash is read by
neither. Folding it in would either break that test or force it to stop
checking, and it is the test that keeps the set honest."""

IMPLEMENTED_KEYWORDS = COMBAT_KEYWORDS | TIMING_KEYWORDS
"""Everything the engine actually does something with. What `fidelity` asks."""
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
    deathtouched: bool = False
    """Has been dealt damage by a deathtouch source this turn (CR 704.5h).

    Kept apart from `damage` because the amount is irrelevant — one point from a
    deathtoucher is lethal to a 10/10, and folding that into the damage number
    would make a 1/1's hit indistinguishable from a real ten points when
    something later heals or pumps toughness."""
    counters: dict[str, int] = field(default_factory=dict)
    power_mod: int = 0
    toughness_mod: int = 0
    """Power and toughness granted until end of turn, kept apart from counters.

    Counters are symmetric by construction — a `+1/+1` counter moves both halves
    by the same amount — so modelling every pump as counters cannot express
    +3/-3, and collapsing it to one number turned Nameless Inversion, a removal
    spell, into a permanent +3/+3 buff. It also made a -5/-0 shrink a no-op.

    These are cleared in the cleanup step, which is what makes "until end of
    turn" mean what it says rather than lasting the rest of the game."""
    summoning_sick: bool = False
    """Set when a permanent enters the battlefield, cleared during its
    controller's untap step. A creature with this cannot attack or pay {T},
    unless it has haste."""
    attached_to: int | None = None
    face_down: bool = False
    granted: set[str] = field(default_factory=set)
    """Keywords granted until end of turn, cleared in cleanup beside the P/T
    modifiers. Kept apart from the card's printed keywords so nothing has to
    mutate a frozen `Card` that other objects share."""
    static_power: int = 0
    static_toughness: int = 0
    """Contribution from static abilities in play, recomputed by `statics.apply`.

    Kept apart from `power_mod`, which is an until-end-of-turn effect that gets
    cleared in cleanup. These are never cleared on a timer — they are rebuilt
    from the battlefield, so an anthem leaving stops applying without anything
    having to remember that it did."""

    is_commander: bool = False
    """Set for the object its owner named as their commander. Survives zone
    changes via `fresh_copy`, unlike everything else on this object — a
    commander that stopped being one on its way to the graveyard would never
    come back to the command zone."""
    trigger: Ability | None = None
    """Set when this stack entry is a triggered ability rather than a card.

    A triggered ability on the stack is its own object (CR 113.7a): it is not
    the permanent, and when it resolves the permanent stays where it is. It
    carries the source card so the effect can name it, and this field so
    resolution knows not to put a creature onto the battlefield twice."""

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
        return ((base or 0) + self.counters.get("+1/+1", 0)
                - self.counters.get("-1/-1", 0) + self.power_mod
                + self.static_power)

    @property
    def toughness(self) -> int:
        base = self.card.base_toughness
        return ((base or 0) + self.counters.get("+1/+1", 0)
                - self.counters.get("-1/-1", 0) + self.toughness_mod
                + self.static_toughness)

    @property
    def lethal_damage(self) -> bool:
        """Toughness 0 or less, or damage marked at least equal to toughness.

        Only meaningful for creatures on the battlefield; the caller checks that.
        """
        if self.deathtouched and self.damage > 0:
            return True
        return self.toughness <= 0 or self.damage >= self.toughness

    def destination_for(self, to: "Zone") -> "Zone":
        """Where this object actually goes — CR 903.9 for a commander.

        A commander headed for a graveyard or exile goes to the command zone
        instead. The rules make it a choice its owner may decline; taking it
        always is the approximation, and declining is only ever right for a deck
        built to recur its commander out of a graveyard, which needs abilities
        this engine does not have.

        Lives on the object rather than in `commander` because `state.move` has
        to ask it, and `commander` reads state — putting it there is a cycle.
        """
        if self.is_commander and to in (Zone.GRAVEYARD, Zone.EXILE):
            return Zone.COMMAND
        return to

    def has(self, keyword: str) -> bool:
        """Printed on the card, or granted to it this turn.

        Read through here rather than off `card` so a granted keyword is
        indistinguishable from a printed one everywhere combat asks — which is
        the whole point, since "gains trample until end of turn" has to make the
        same trample the printed one does.
        """
        return self.card.has(keyword) or keyword.lower() in self.granted

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
            is_commander=self.is_commander,
        )

    @property
    def is_blocked(self) -> bool:
        return bool(self.blocked_by)

    def leave_combat(self) -> None:
        self.attacking = None
        self.blocking = None
        self.blocked_by = ()

    def clone(self) -> "GameObject":
        return replace(self, counters=dict(self.counters),
                       granted=set(self.granted))

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
