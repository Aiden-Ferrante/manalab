"""Running an optimizer and getting a trace back."""

from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

from manalab.search.oracle import Oracle, crn_base_for_run
from manalab.search.problem import Problem
from manalab.search.trace import Trace


@runtime_checkable
class Optimizer(Protocol):
    """Search strategies implement this and nothing else.

    `run` gets an `Oracle` — never a `Problem`, never an `Evaluator`. Everything
    it can learn about the objective comes from spending budget, which is what
    makes the comparison in Phase 4 fair.

    Implementations must be pure in `(oracle.seed, config)`: all randomness comes
    from `oracle.rng`, never the global `random` module.
    """

    name: str

    def run(self, oracle: Oracle) -> tuple[int, ...]:
        """Search, then return the vector you would ship."""

    def config(self) -> Mapping[str, Any]:
        """Hyperparameters, for the results store and the trace digest."""


def run_optimizer(
    problem: Problem,
    optimizer: Optimizer,
    *,
    budget: int,
    seed: int,
    crn_seed: int | None = None,
) -> Trace:
    """Execute one optimizer run. The unit of the benchmark.

    By default each `seed` gets its own block of random streams, so replicating
    across seeds varies the games as well as the optimizer's own choices. Pass an
    explicit `crn_seed` to pin every run to the same games — useful for isolating
    optimizer variance, misleading for anything else.
    """
    oracle = Oracle(
        problem,
        budget=budget,
        seed=seed,
        crn_seed=crn_base_for_run(seed) if crn_seed is None else crn_seed,
    )
    oracle.trace.optimizer = optimizer.name
    oracle.trace.config = dict(optimizer.config())

    final = optimizer.run(oracle)

    if not problem.is_feasible(tuple(final)):
        raise ValueError(f"{optimizer.name} returned an infeasible deck")

    oracle.trace.config = {
        **oracle.trace.config,
        "final_vector": list(final),
        "crn_seed": oracle.crn_seed,
        "unmodeled_cards": sorted(oracle.unmodeled),
    }
    return oracle.trace
