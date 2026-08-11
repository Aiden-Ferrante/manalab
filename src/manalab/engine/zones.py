"""Zones, and who owns them.

Magic has seven zones with meaningfully different rules. Two distinctions drive
the whole design:

**Private zones belong to a player** (library, hand, graveyard) — every player
has their own. **Shared zones do not** (battlefield, stack, exile, command);
objects there carry a controller instead.

**A card that changes zones becomes a new object** (CR 400.7). It forgets its
damage, counters, tapped status, and every effect that was tracking it. That is
not an implementation convenience — it is the rule that makes "destroy it, then
return it" not restore auras, and getting it wrong breaks interactions
everywhere. `GameState.move` mints a fresh id on every zone change to enforce it.
"""

from __future__ import annotations

from enum import StrEnum


class Zone(StrEnum):
    LIBRARY = "library"
    HAND = "hand"
    BATTLEFIELD = "battlefield"
    GRAVEYARD = "graveyard"
    EXILE = "exile"
    STACK = "stack"
    COMMAND = "command"


PRIVATE = frozenset({Zone.LIBRARY, Zone.HAND, Zone.GRAVEYARD})
"""Zones each player has their own copy of."""

SHARED = frozenset({Zone.BATTLEFIELD, Zone.STACK, Zone.EXILE, Zone.COMMAND})

ORDERED = frozenset({Zone.LIBRARY, Zone.GRAVEYARD, Zone.STACK})
"""Zones where order is part of the game state.

Hand and battlefield are unordered in the rules; we still store them as lists so
that iteration is deterministic, but nothing may depend on their order.
"""

HIDDEN = frozenset({Zone.LIBRARY, Zone.HAND})
"""Zones a player cannot see into. Matters for agents later — an agent reading
the opponent's hand is cheating, and the type system should make that visible.
"""


def owner_of_zone(zone: Zone, obj_owner: int, controller: int) -> int | None:
    """Which player's copy of `zone` an object goes to.

    Private zones always take the object's *owner*, never its controller — a
    creature you stole and then killed goes to its owner's graveyard (CR 400.3).
    Getting this backwards silently steals cards.
    """
    if zone in PRIVATE:
        return obj_owner
    return None
