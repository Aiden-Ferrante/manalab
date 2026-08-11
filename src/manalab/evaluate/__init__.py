"""L2 — the seam. Everything above this line is fidelity-independent.

An `Evaluator` turns a decklist into numbers. It is the *only* thing the search
layer is allowed to know about Magic. Two implementations exist behind it: the
goldfish model in `manalab.game` and (in time) the rules engine in
`manalab.engine`. Search must not be able to tell the difference except by
reading `EvalResult.evaluator`.

This module is a **facade only** — it re-exports and defines nothing. The
protocol and result types live in `result.py` so that sibling modules can import
them directly. A package `__init__` that holds real code forces its own
submodules to import through it, which is exactly how the engine package grew a
four-module import cycle. See ADR 0005.
"""

from manalab.evaluate.result import (
    EvalResult,
    Evaluator,
    Objective,
    metric,
    weighted,
)

__all__ = [
    "EvalResult",
    "Evaluator",
    "Objective",
    "metric",
    "weighted",
]
