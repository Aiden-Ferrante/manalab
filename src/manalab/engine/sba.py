"""State-based actions (CR 704).

These are not effects and never use the stack: the game checks them whenever a
player would receive priority, and applies all applicable ones simultaneously,
repeating until none apply. That repetition matters — one creature dying can put
another below zero toughness, and a single pass would leave the game in an
illegal state.

Implemented: player loss (life, empty draw, poison), creature death by lethal
damage or non-positive toughness, and planeswalkers at zero loyalty. Not yet:
legend rule, auras with illegal attachments, token cleanup.
"""

from __future__ import annotations

from manalab.engine.state import GameState
from manalab.engine.zones import Zone

MAX_POISON = 10


def check(state: GameState) -> list[str]:
    """Apply state-based actions until none apply. Returns what happened."""
    events: list[str] = []

    for _ in range(100):  # a fixed point is reached in a handful of rounds
        applied = _one_pass(state)
        if not applied:
            break
        events.extend(applied)
    else:  # pragma: no cover - would mean SBAs are oscillating
        raise RuntimeError("state-based actions did not converge")

    return events


def _one_pass(state: GameState) -> list[str]:
    applied: list[str] = []

    # 704.5a/b/c — players lose. Checked before creatures die so that a player
    # already at zero does not get to see the board resolve first.
    for player in state.players:
        if player.has_lost:
            continue
        if player.life <= 0:
            player.has_lost, player.loss_reason = True, "life"
        elif player.drew_from_empty:
            player.has_lost, player.loss_reason = True, "empty library"
        elif player.poison >= MAX_POISON:
            player.has_lost, player.loss_reason = True, "poison"
        else:
            continue
        applied.append(f"{player.name} loses ({player.loss_reason})")

    # 704.5f/g — creatures with lethal damage or zero toughness are destroyed.
    # Collected before moving anything: mutating the battlefield while iterating
    # it would skip creatures.
    doomed = [
        obj
        for obj in state.battlefield()
        if obj.is_creature and obj.card.base_toughness is not None and obj.lethal_damage
    ]
    for obj in doomed:
        state.move(obj, Zone.GRAVEYARD)
        applied.append(f"{obj.card.name} dies")

    # 704.5i — planeswalkers with no loyalty.
    for obj in list(state.battlefield()):
        if "Planeswalker" in obj.types and obj.counters.get("loyalty", 0) <= 0:
            state.move(obj, Zone.GRAVEYARD)
            applied.append(f"{obj.card.name} dies (no loyalty)")

    return applied


def winner(state: GameState) -> int | None:
    """The sole surviving player, or None while the game continues.

    Returns None for a draw as well, which the caller distinguishes by checking
    whether anyone is left standing.
    """
    alive = [p.index for p in state.players if not p.has_lost]
    return alive[0] if len(alive) == 1 else None


def game_over(state: GameState) -> bool:
    return sum(1 for p in state.players if not p.has_lost) <= 1
