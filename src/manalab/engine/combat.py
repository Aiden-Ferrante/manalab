"""Blocking legality and combat damage assignment.

Split out of `game.py` because the driver is meant to stay a driver. Everything
here answers one of two questions: *may this creature block that one*, and *who
takes how much damage*.

The keywords implemented here are the ones that change combat arithmetic:
flying, reach, menace, trample, deathtouch, first strike, double strike and
lifelink. Vigilance, defender and haste are handled elsewhere because they
affect declaration and tapping rather than damage.

Two deliberate approximations, both bounded and both reported:

  * **Damage assignment order is fixed** (the order blockers were declared)
    rather than chosen by the attacking player. This matters only when an
    attacker is blocked by several creatures and cannot kill them all.
  * **First strike runs as two passes inside the combat damage step** rather
    than as a separate step with its own priority window. Nothing can be cast
    in the gap today, so the only observable difference is that state-based
    actions run between the passes — which they do.
"""

from __future__ import annotations

from typing import Iterable, Sequence

import manalab.engine.commander as commander
import manalab.engine.triggers as triggers
from manalab.engine.objects import GameObject
from manalab.engine.state import GameState
from manalab.engine.zones import Zone

MAX_BLOCK_OPTIONS = 2048
"""Cap on enumerated block assignments.

The assignment space is (attackers + 1) ^ blockers, so a ten-on-ten board is
tens of millions of options. Past this cap the least powerful blockers are
frozen as non-blockers until the space fits, which is a restriction of the
defender's choices — never an illegal option offered. `blocks_truncated` says
when it happened so a caller can tell a considered no-block from a forced one.
"""


def can_block(blocker: GameObject, attacker: GameObject) -> bool:
    """Evasion only (CR 509.1b). Tapped-ness is the caller's check.

    Menace is not here: "can't be blocked except by two or more" is a property
    of the whole assignment, not of one pairing, so it is enforced in
    `legal_blocks` once the full assignment is known.
    """
    if attacker.has("Flying") and not (blocker.has("Flying") or blocker.has("Reach")):
        return False
    return True


def _menace_satisfied(attacker: GameObject, n_blockers: int) -> bool:
    """CR 702.110a — blocked by exactly one is the illegal case, zero is fine."""
    if not attacker.has("Menace"):
        return True
    return n_blockers != 1


def legal_blocks(
    state: GameState, player: int, attacker_ids: Sequence[int]
) -> tuple[list[tuple[tuple[int, int], ...]], bool]:
    """Every legal block assignment, as (blocker_id, attacker_id) tuples.

    Returns `(assignments, truncated)`. Each assignment is complete: a blocker
    absent from it is simply not blocking. Multiple blockers may block the same
    attacker, and different blockers may block different attackers — the thing
    the single-pair enumerator this replaced could not express, and the reason a
    wide board used to be unanswerable.
    """
    able = [obj for obj in state.creatures(player) if not obj.tapped]
    attackers = [state.objects[i] for i in attacker_ids if i in state.objects]
    if not able or not attackers:
        return [()], False

    # Weakest blockers lose their choices first when the space is too large:
    # a 1/1 declining to block costs the defender less than a 6/6 doing so.
    able.sort(key=lambda o: (o.power, o.toughness), reverse=True)

    truncated = False
    choices: list[tuple[int, list[int | None]]] = []
    space = 1
    for blocker in able:
        options: list[int | None] = [None]
        options.extend(a.id for a in attackers if can_block(blocker, a))
        if space * len(options) > MAX_BLOCK_OPTIONS:
            truncated = True
            options = [None]
        space *= len(options)
        choices.append((blocker.id, options))

    assignments: list[tuple[tuple[int, int], ...]] = []
    _expand(choices, 0, (), assignments)

    by_id = {a.id: a for a in attackers}
    legal = [a for a in assignments if _assignment_legal(a, by_id)]
    return legal, truncated


def _expand(
    choices: Sequence[tuple[int, list[int | None]]],
    index: int,
    acc: tuple[tuple[int, int], ...],
    out: list[tuple[tuple[int, int], ...]],
) -> None:
    if index == len(choices):
        out.append(acc)
        return
    blocker_id, options = choices[index]
    for target in options:
        nxt = acc if target is None else acc + ((blocker_id, target),)
        _expand(choices, index + 1, nxt, out)


def _assignment_legal(
    assignment: tuple[tuple[int, int], ...], attackers: dict[int, GameObject]
) -> bool:
    counts: dict[int, int] = {}
    for _, attacker_id in assignment:
        counts[attacker_id] = counts.get(attacker_id, 0) + 1
    return all(
        _menace_satisfied(attackers[attacker_id], n) for attacker_id, n in counts.items()
    )


# --- damage -------------------------------------------------------------


def deals_damage_in(obj: GameObject, *, first_strike_pass: bool) -> bool:
    """Which of the two damage passes this creature deals in (CR 510.5).

    Double strike deals in both. Ordinary creatures deal only in the regular
    pass, first strikers only in the first.
    """
    first = obj.has("First strike") or obj.has("Double strike")
    if first_strike_pass:
        return first
    return not first or obj.has("Double strike")


def any_first_strike(attackers: Iterable[GameObject], state: GameState) -> bool:
    """Whether a first-strike pass is needed at all.

    Checked over attackers *and* their blockers, since a first-striking blocker
    matters just as much as a first-striking attacker.
    """
    for attacker in attackers:
        if attacker.has("First strike") or attacker.has("Double strike"):
            return True
        for blocker_id in attacker.blocked_by:
            blocker = state.objects.get(blocker_id)
            if blocker is not None and (
                blocker.has("First strike") or blocker.has("Double strike")
            ):
                return True
    return False


def _lethal_for(blocker: GameObject, source: GameObject) -> int:
    """Damage needed to count as lethal when assigning (CR 510.1a).

    One point is lethal from a deathtouch source no matter the toughness, which
    is what lets a 1/1 deathtoucher eat a 10/10 and still trample for nine.
    """
    if source.has("Deathtouch"):
        return 1
    return max(0, blocker.toughness - blocker.damage)


def _hit(target: GameObject, amount: int, source: GameObject) -> None:
    if amount <= 0:
        return
    target.damage += amount
    if source.has("Deathtouch"):
        target.deathtouched = True


def combat_damage(
    state: GameState, attackers: Sequence[GameObject], *, first_strike_pass: bool
) -> list[str]:
    """One pass of combat damage, applied simultaneously (CR 510.2).

    Every hit is computed against the board as it stands at the start of the
    pass and applied only afterwards, so a creature that dies here still dealt
    its damage. Getting that wrong is the classic engine bug where the attacker
    with higher power silently wins every trade.
    """
    log: list[str] = []
    pending: list[tuple[GameObject, int, GameObject]] = []
    life_gain: dict[int, int] = {}
    player_damage: dict[int, int] = {}

    def deal_to_player(player: int, amount: int, source: GameObject) -> None:
        if amount <= 0:
            return
        player_damage[player] = player_damage.get(player, 0) + amount
        if source.has("Lifelink"):
            life_gain[source.controller] = life_gain.get(source.controller, 0) + amount

    for attacker in attackers:
        if attacker.zone is not Zone.BATTLEFIELD:
            continue

        blockers = [
            state.objects[b]
            for b in attacker.blocked_by
            if b in state.objects and state.objects[b].zone is Zone.BATTLEFIELD
        ]

        # Blockers strike back regardless of whether the attacker is still able
        # to deal damage this pass.
        for blocker in blockers:
            if deals_damage_in(blocker, first_strike_pass=first_strike_pass):
                pending.append((attacker, blocker.power, blocker))
                if blocker.has("Lifelink") and blocker.power > 0:
                    life_gain[blocker.controller] = (
                        life_gain.get(blocker.controller, 0) + blocker.power
                    )

        if not deals_damage_in(attacker, first_strike_pass=first_strike_pass):
            continue

        if not attacker.is_blocked:
            deal_to_player(attacker.attacking, attacker.power, attacker)
            commander.deal_commander_damage(
                state, attacker.attacking, attacker, attacker.power)
            state.events.append(triggers.Event(
                triggers.EventKind.COMBAT_DAMAGE_TO_PLAYER,
                attacker.id, attacker.controller))
            log.append(
                f"{attacker.card.name} hits P{attacker.attacking} for {attacker.power}"
            )
            continue

        # Blocked. Assign lethal down the line, then spill.
        remaining = attacker.power
        for blocker in blockers:
            if remaining <= 0:
                break
            amount = min(remaining, _lethal_for(blocker, attacker))
            pending.append((blocker, amount, attacker))
            remaining -= amount
            if attacker.has("Lifelink"):
                life_gain[attacker.controller] = (
                    life_gain.get(attacker.controller, 0) + amount
                )

        if remaining > 0:
            if attacker.has("Trample"):
                deal_to_player(attacker.attacking, remaining, attacker)
                commander.deal_commander_damage(
                    state, attacker.attacking, attacker, remaining)
                state.events.append(triggers.Event(
                    triggers.EventKind.COMBAT_DAMAGE_TO_PLAYER,
                    attacker.id, attacker.controller))
                log.append(f"{attacker.card.name} tramples over for {remaining}")
            elif blockers:
                # Excess must still be assigned to something it is blocked by.
                pending.append((blockers[-1], remaining, attacker))
                if attacker.has("Lifelink"):
                    life_gain[attacker.controller] = (
                        life_gain.get(attacker.controller, 0) + remaining
                    )

    for target, amount, source in pending:
        _hit(target, amount, source)

    for player, amount in player_damage.items():
        state.players[player].lose_life(amount)

    for player, amount in life_gain.items():
        state.players[player].gain_life(amount)
        log.append(f"P{player} gains {amount} (lifelink)")

    return log
