"""L1 — the game model. May import `manalab.cards` and nothing else from manalab.

Exposes per-game *records*, never live game state. Nothing outside this package
may hold a reference to a game in progress; that is what keeps the simulator
replaceable.
"""

from manalab.game.goldfish import GameRecord, play, scan_unmodeled
from manalab.game.library import resolve, shuffle
from manalab.game.mana import assign, can_pay
from manalab.game.mulligan import bottom_worst, land_window_keep, mulligan

__all__ = [
    "GameRecord",
    "assign",
    "bottom_worst",
    "can_pay",
    "land_window_keep",
    "mulligan",
    "play",
    "resolve",
    "scan_unmodeled",
    "shuffle",
]
