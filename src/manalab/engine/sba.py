"""State-based actions (CR 704).

These are not effects and never use the stack: the game checks them whenever a
player would receive priority, and applies all applicable ones simultaneously,
repeating until none apply. That repetition matters — one creature dying can put
another below zero toughness, and a single pass would leave the game in an
illegal state.

Implemented: player loss (life, empty draw, poison), creature death by lethal
damage or non-positive toughness, planeswalkers at zero loyalty, and the
legend rule. Not yet: auras with illegal attachments, token cleanup.
"""

from __future__ import annotations

import manalab.engine.commander as commander
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
        elif commander.lethal_commander_damage(state, player.index):
            # CR 903.10a. Checked beside the other loss conditions rather
            # than in combat, because it is a state-based action and a
            # player can reach 21 from a source that is not combat damage.
            player.has_lost, player.loss_reason = True, "commander damage"
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

    applied.extend(_legend_rule(state))
    return applied


def _legend_rule(state: GameState) -> list[str]:
    """704.5j — one legendary permanent per name per player.

    Without this a search happily plays four copies of a legend it should play
    one of, because extra copies are strictly better here and strictly worse in
    Magic. That is not a hypothetical: a GA run came back with three copies of a
    legendary 9/7, and `fidelity` had to refuse all 309 legends in the mono-green
    pool — every possible commander among them — to keep them out.

    **The choice of which copy survives is not offered to the agent.** The rules
    let the controller pick; this keeps the oldest (lowest id) and bins the rest.
    That is a real approximation, and it is only visible when the copies differ —
    one is tapped, damaged, or carrying counters. It is deterministic, which
    matters more here: common random numbers require that the same seed produce
    the same game.
    """
    applied: list[str] = []
    seen: dict[tuple[int, str], int] = {}

    for obj in sorted(state.battlefield(), key=lambda o: o.id):
        if "Legendary" not in obj.types:
            continue
        key = (obj.controller, obj.name)
        if key not in seen:
            seen[key] = obj.id
            continue
        state.move(obj, Zone.GRAVEYARD)
        applied.append(f"{obj.card.name} dies (legend rule)")

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
