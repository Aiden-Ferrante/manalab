"""The game state, and zone movement as the single mutation primitive.

Everything that happens in Magic bottoms out in objects changing zones, and
routing every such change through one method is what keeps the engine
trustworthy as verbs are added: triggers, replacement effects, and object
identity all hook in at exactly one place.

The state is **mutable**. Immutable-with-structural-sharing would be nicer for
tree search, but in Python it costs more than it saves at this size. `clone()`
gives a deep-enough copy for lookahead instead, and is the seam to optimise if
search ever needs it.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Iterable, Iterator, Sequence

from manalab.cards.model import Card
from manalab.engine.objects import GameObject
from manalab.engine.player import Player
from manalab.engine.zones import ORDERED, PRIVATE, Zone, owner_of_zone

ZoneKey = tuple[Zone, int | None]


@dataclass
class GameState:
    players: list[Player]
    objects: dict[int, GameObject] = field(default_factory=dict)
    zones: dict[ZoneKey, list[int]] = field(default_factory=dict)
    turn: int = 0
    active_player: int = 0
    next_id: int = 1
    rng: random.Random = field(default_factory=lambda: random.Random(0))
    log: list[str] = field(default_factory=list)

    # --- construction ---------------------------------------------------

    @classmethod
    def new(
        cls,
        libraries: Sequence[Sequence[Card]],
        *,
        seed: int = 0,
        names: Sequence[str] | None = None,
        starting_life: int = 20,
    ) -> "GameState":
        """A game with each player's library in the given order (not shuffled)."""
        players = [
            Player(index=i, name=(names[i] if names else f"P{i}"), life=starting_life)
            for i in range(len(libraries))
        ]
        state = cls(players=players, rng=random.Random(seed))

        for index, library in enumerate(libraries):
            for card in library:
                state.create(card, owner=index, zone=Zone.LIBRARY)
        return state

    def create(self, card: Card, *, owner: int, zone: Zone, controller: int | None = None) -> GameObject:
        """Put a brand-new object into a zone. Used at setup and by token effects."""
        obj = GameObject(
            id=self._mint(),
            card=card,
            owner=owner,
            controller=owner if controller is None else controller,
            zone=zone,
        )
        self.objects[obj.id] = obj
        self._zone_list(zone, obj).append(obj.id)
        return obj

    def _mint(self) -> int:
        self.next_id += 1
        return self.next_id - 1

    # --- zone access ----------------------------------------------------

    def _zone_list(self, zone: Zone, obj: GameObject) -> list[int]:
        key: ZoneKey = (zone, owner_of_zone(zone, obj.owner, obj.controller))
        return self.zones.setdefault(key, [])

    def zone(self, zone: Zone, player: int | None = None) -> list[GameObject]:
        """Objects in a zone, in order. Pass `player` for private zones."""
        key: ZoneKey = (zone, player if zone in PRIVATE else None)
        return [self.objects[i] for i in self.zones.get(key, [])]

    def battlefield(self, controller: int | None = None) -> list[GameObject]:
        objs = self.zone(Zone.BATTLEFIELD)
        return objs if controller is None else [o for o in objs if o.controller == controller]

    def hand(self, player: int) -> list[GameObject]:
        return self.zone(Zone.HAND, player)

    def library(self, player: int) -> list[GameObject]:
        return self.zone(Zone.LIBRARY, player)

    def graveyard(self, player: int) -> list[GameObject]:
        return self.zone(Zone.GRAVEYARD, player)

    def creatures(self, controller: int | None = None) -> list[GameObject]:
        return [o for o in self.battlefield(controller) if o.is_creature]

    # --- the single mutation primitive ----------------------------------

    def move(
        self,
        obj: GameObject | int,
        to: Zone,
        *,
        controller: int | None = None,
        to_top: bool = False,
    ) -> GameObject:
        """Move an object to another zone. Returns the **new** object.

        The returned object has a different id and none of the old one's damage,
        counters or tapped status, because a card changing zones becomes a new
        object (CR 400.7). Callers holding the old reference are holding
        something that no longer exists — which is exactly the bug this
        signature is shaped to surface.
        """
        old = self.objects[obj] if isinstance(obj, int) else obj
        if old.id not in self.objects:
            raise KeyError(f"{old!r} is not in the game (already moved?)")

        self._zone_list(old.zone, old).remove(old.id)
        del self.objects[old.id]

        # Private zones take the owner's copy regardless of who controlled it.
        new_controller = old.owner if to in PRIVATE else (controller or old.controller)
        new = old.fresh_copy(self._mint(), to, new_controller)

        if to == Zone.BATTLEFIELD:
            new.summoning_sick = True
            new.tapped = new.card.enters_tapped

        self.objects[new.id] = new
        destination = self._zone_list(to, new)
        destination.insert(0, new.id) if to_top else destination.append(new.id)

        self.log.append(f"{old.card.name}: {old.zone} -> {to}")
        return new

    # --- common operations ----------------------------------------------

    def shuffle(self, player: int) -> None:
        key: ZoneKey = (Zone.LIBRARY, player)
        ids = self.zones.setdefault(key, [])
        self.rng.shuffle(ids)

    def draw(self, player: int, n: int = 1) -> list[GameObject]:
        """Draw from the top of the library.

        Drawing from an empty library does not lose the game here — it sets a
        flag that state-based actions read later (CR 704.5b). A player who draws
        their last card and then wins before SBAs run has not lost.
        """
        drawn: list[GameObject] = []
        for _ in range(n):
            library = self.zones.get((Zone.LIBRARY, player), [])
            if not library:
                self.players[player].drew_from_empty = True
                break
            drawn.append(self.move(self.objects[library[0]], Zone.HAND))
        return drawn

    def untap_all(self, player: int) -> None:
        for obj in self.battlefield(player):
            obj.tapped = False
            obj.summoning_sick = False

    def find(self, name: str, zone: Zone | None = None, player: int | None = None) -> GameObject | None:
        """First object with this card name. Test and debugging convenience."""
        for obj in self.objects.values():
            if obj.card.name != name:
                continue
            if zone is not None and obj.zone != zone:
                continue
            if player is not None and obj.controller != player:
                continue
            return obj
        return None

    # --- lookahead ------------------------------------------------------

    def clone(self) -> "GameState":
        """Independent copy. The seam to optimise if tree search needs it."""
        copy = GameState(
            players=[p.clone() for p in self.players],
            objects={i: o.clone() for i, o in self.objects.items()},
            zones={k: list(v) for k, v in self.zones.items()},
            turn=self.turn,
            active_player=self.active_player,
            next_id=self.next_id,
            rng=random.Random(),
            log=list(self.log),
        )
        copy.rng.setstate(self.rng.getstate())
        return copy

    def __repr__(self) -> str:
        return (
            f"<GameState turn={self.turn} active={self.active_player} "
            f"{' | '.join(repr(p) for p in self.players)}>"
        )
