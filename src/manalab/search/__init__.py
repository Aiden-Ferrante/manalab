"""L3 — deckbuilding search. May import `manalab.cards` and `manalab.evaluate`.

**Never imports `manalab.game`.** Optimizers reach the game only through the
`Evaluator` protocol, wrapped in an `Oracle` that meters budget and records
every measurement. That is what makes swapping in a full rules engine later a
drop-in rather than a rewrite, and it is enforced by
`tests/test_architecture.py`.

The deliverable of this package is not an optimizer. It is a ranked, defensible
comparison of optimization techniques on the deckbuilding problem — see
`docs/M2_PROMPT.md`. On a noisy objective every optimizer reports success; the
benchmark is what says which one is right.

Phase status:
  0. harness ....................... this module, `oracle`, `trace`, `budget`, `store`
  1. ground truth and baselines .... `baselines`, `problems`
  2. variance reduction ............ not started
  3. budget allocation ............. not started
  4. search strategies ............. not started
  5. objectives .................... `objective` (scalar only so far)
  6. statistical validity .......... not started
  7. interpretation ................ not started
"""

from manalab.search.budget import BudgetExceeded, BudgetMeter
from manalab.search.objective import CONSISTENCY, LinearObjective
from manalab.search.oracle import DEFAULT_CRN_SEED, Oracle
from manalab.search.problem import Problem
from manalab.search.runner import Optimizer, run_optimizer
from manalab.search.trace import Estimate, Evaluation, Trace

__all__ = [
    "CONSISTENCY",
    "DEFAULT_CRN_SEED",
    "BudgetExceeded",
    "BudgetMeter",
    "Estimate",
    "Evaluation",
    "LinearObjective",
    "Optimizer",
    "Oracle",
    "Problem",
    "Trace",
    "run_optimizer",
]
