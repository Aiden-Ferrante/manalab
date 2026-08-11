"""Budget accounting, in simulated games.

Wall clock is not the unit. Two optimizers compared on elapsed time reward
whichever happened to get the faster code path, cache behaviour or CPU; the
question M2 asks is what each does with a fixed number of simulated games.

Overruns raise. A warning would let a run finish and quietly poison a
comparison, and the whole benchmark rests on budgets being equal.
"""

from __future__ import annotations


class BudgetExceeded(RuntimeError):
    """Raised when an optimizer tries to spend past its allocation."""


class BudgetMeter:
    def __init__(self, total: int) -> None:
        if total <= 0:
            raise ValueError("budget must be positive")
        self._total = total
        self._spent = 0

    @property
    def total(self) -> int:
        return self._total

    @property
    def spent(self) -> int:
        return self._spent

    @property
    def remaining(self) -> int:
        return self._total - self._spent

    @property
    def exhausted(self) -> bool:
        return self._spent >= self._total

    def can_afford(self, games: int) -> bool:
        return games <= self.remaining

    def spend(self, games: int) -> None:
        if games < 0:
            raise ValueError("cannot spend negative games")
        if games > self.remaining:
            raise BudgetExceeded(
                f"tried to spend {games} games with {self.remaining} of "
                f"{self._total} remaining"
            )
        self._spent += games

    def clamp(self, games: int) -> int:
        """Largest affordable spend up to `games`. Zero when exhausted.

        For optimizers that would rather shrink a final batch than raise.
        """
        return max(0, min(games, self.remaining))

    def __repr__(self) -> str:
        return f"BudgetMeter(spent={self._spent}, total={self._total})"
