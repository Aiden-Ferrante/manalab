"""What an optimizer is pointed at.

A `Problem` bundles the search space, the noisy oracle, and what "good" means.
It holds an `Evaluator` but never a `Card`: optimizers work on integer vectors
over a `CandidatePool` and read scores back. That is the whole interface, and it
is what lets a Forge-backed evaluator drop in later without touching search.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from manalab.cards.model import CandidatePool, Decklist
from manalab.evaluate.result import Evaluator
from manalab.search.objective import LinearObjective


@dataclass(frozen=True)
class Problem:
    pool: CandidatePool
    evaluator: Evaluator
    objective: LinearObjective
    start: tuple[int, ...] | None = None
    """Optional starting deck as a count vector. `None` means the optimizer picks."""
    name: str = ""

    def __post_init__(self) -> None:
        if self.start is not None:
            if len(self.start) != len(self.pool.card_ids):
                raise ValueError("start vector does not match pool size")
            if not self.is_feasible(self.start):
                raise ValueError("start vector is not a feasible deck")
        if not self.name:
            object.__setattr__(
                self, "name", f"{len(self.pool.card_ids)}cards/{self.pool.deck_size}"
            )

    @property
    def dimension(self) -> int:
        return len(self.pool.card_ids)

    def is_feasible(self, vector: tuple[int, ...]) -> bool:
        if sum(vector) != self.pool.deck_size:
            return False
        return all(0 <= v <= u for v, u in zip(vector, self.pool.upper_bounds))

    def to_decklist(self, vector: tuple[int, ...], name: str = "") -> Decklist:
        return self.pool.from_vector(vector, name)

    def descriptor(self) -> Mapping[str, Any]:
        """Stable identity of the problem, for the results store."""
        return {
            "name": self.name,
            "pool": list(self.pool.card_ids),
            "deck_size": self.pool.deck_size,
            "upper_bounds": list(self.pool.upper_bounds),
            "evaluator": getattr(self.evaluator, "name", type(self.evaluator).__name__),
            "objective": self.objective.name,
            "start": list(self.start) if self.start is not None else None,
        }
