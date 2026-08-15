"""Players: life, per-turn allowances, and how they lose."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

STARTING_LIFE = 20


@dataclass
class Player:
    index: int
    name: str = ""
    life: int = STARTING_LIFE
    counters: dict[str, int] = field(default_factory=dict)
    """Poison, energy, experience. Not life — life is not a counter."""

    lands_played: int = 0
    land_drops: int = 1
    """Per turn. A field rather than a constant because Exploration exists."""

    commander_casts: int = 0
    """How many times this player has cast their commander from the command
    zone. Each one makes the next cost {2} more (CR 903.8)."""
    commander_damage: dict[str, int] = field(default_factory=dict)
    """Damage taken from each commander, by name. Tracked per source because 20
    from one and 20 from another is not a loss, and a single total would make it
    one (CR 903.10a)."""

    has_lost: bool = False
    loss_reason: str = ""
    drew_from_empty: bool = False
    """Set when a draw is attempted from an empty library. The player does not
    lose immediately — they lose the next time state-based actions are checked
    (CR 704.5b), which is why this is a flag and not an instant loss."""

    def __post_init__(self) -> None:
        if not self.name:
            self.name = f"P{self.index}"

    @property
    def poison(self) -> int:
        return self.counters.get("poison", 0)

    def gain_life(self, n: int) -> None:
        self.life += n

    def lose_life(self, n: int) -> None:
        self.life -= n

    def can_play_land(self) -> bool:
        return self.lands_played < self.land_drops

    def begin_turn(self) -> None:
        self.lands_played = 0

    def add_counters(self, kind: str, n: int = 1) -> None:
        self.counters[kind] = self.counters.get(kind, 0) + n
        if self.counters[kind] <= 0:
            self.counters.pop(kind, None)

    def clone(self) -> "Player":
        return replace(self, counters=dict(self.counters))

    def __repr__(self) -> str:
        state = "LOST" if self.has_lost else f"{self.life} life"
        return f"<{self.name} {state}>"
