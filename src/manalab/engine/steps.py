"""The turn: five phases, twelve steps, and who gets priority when.

Two steps are special and both are common sources of bugs:

  UNTAP    — no player receives priority (CR 502.4). Nothing can be cast here.
  CLEANUP  — no priority either, *unless* something triggers or a player has to
             discard, in which case an extra cleanup step follows (CR 514.3a).

Everywhere else the active player receives priority first, and a step ends only
when every player passes in succession on an empty stack.
"""

from __future__ import annotations

from enum import StrEnum


class Phase(StrEnum):
    BEGINNING = "beginning"
    PRECOMBAT_MAIN = "precombat main"
    COMBAT = "combat"
    POSTCOMBAT_MAIN = "postcombat main"
    ENDING = "ending"


class Step(StrEnum):
    UNTAP = "untap"
    UPKEEP = "upkeep"
    DRAW = "draw"
    PRECOMBAT_MAIN = "precombat main"
    BEGIN_COMBAT = "beginning of combat"
    DECLARE_ATTACKERS = "declare attackers"
    DECLARE_BLOCKERS = "declare blockers"
    COMBAT_DAMAGE = "combat damage"
    END_COMBAT = "end of combat"
    POSTCOMBAT_MAIN = "postcombat main"
    END = "end"
    CLEANUP = "cleanup"


TURN: tuple[Step, ...] = (
    Step.UNTAP,
    Step.UPKEEP,
    Step.DRAW,
    Step.PRECOMBAT_MAIN,
    Step.BEGIN_COMBAT,
    Step.DECLARE_ATTACKERS,
    Step.DECLARE_BLOCKERS,
    Step.COMBAT_DAMAGE,
    Step.END_COMBAT,
    Step.POSTCOMBAT_MAIN,
    Step.END,
    Step.CLEANUP,
)

PHASE_OF: dict[Step, Phase] = {
    Step.UNTAP: Phase.BEGINNING,
    Step.UPKEEP: Phase.BEGINNING,
    Step.DRAW: Phase.BEGINNING,
    Step.PRECOMBAT_MAIN: Phase.PRECOMBAT_MAIN,
    Step.BEGIN_COMBAT: Phase.COMBAT,
    Step.DECLARE_ATTACKERS: Phase.COMBAT,
    Step.DECLARE_BLOCKERS: Phase.COMBAT,
    Step.COMBAT_DAMAGE: Phase.COMBAT,
    Step.END_COMBAT: Phase.COMBAT,
    Step.POSTCOMBAT_MAIN: Phase.POSTCOMBAT_MAIN,
    Step.END: Phase.ENDING,
    Step.CLEANUP: Phase.ENDING,
}

NO_PRIORITY = frozenset({Step.UNTAP, Step.CLEANUP})
MAIN_STEPS = frozenset({Step.PRECOMBAT_MAIN, Step.POSTCOMBAT_MAIN})
COMBAT_STEPS = frozenset(s for s, p in PHASE_OF.items() if p is Phase.COMBAT)


def next_step(step: Step) -> Step | None:
    """The following step, or None at end of turn."""
    index = TURN.index(step)
    return TURN[index + 1] if index + 1 < len(TURN) else None


def is_sorcery_speed(step: Step, active: bool, stack_empty: bool) -> bool:
    """Can a sorcery-speed spell be cast right now? (CR 307.1)

    Your own main phase, empty stack, and you hold priority. Every one of those
    three conditions is load-bearing — dropping the stack check is the classic
    way to let a sorcery be cast in response to something.
    """
    return active and stack_empty and step in MAIN_STEPS
