"""The experimental record.

A `Trace` is every evaluation an optimizer made, in order, with what it cost.
Anything not in the trace did not happen: claims about an optimizer's behaviour
have to be re-derivable from this object alone, months later, without the code
that produced it.

`digest()` is the reproducibility check. Two runs of the same optimizer at the
same seed must produce the same digest, or something in the stack is reading
unseeded randomness.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any, Iterator, Mapping, Sequence


@dataclass(frozen=True)
class Estimate:
    """One measurement of one deck."""

    vector: tuple[int, ...]
    score: float
    stderr: float
    games: int
    """Precision of this estimate — total games behind it, not the incremental
    spend. Derive the marginal cost from consecutive `cumulative_games`."""
    stream: int
    """Which random stream produced it. Two estimates sharing a stream are paired
    by common random numbers; two on different streams are independent."""

    def ci95(self) -> tuple[float, float]:
        return (self.score - 1.96 * self.stderr, self.score + 1.96 * self.stderr)

    def as_row(self) -> dict[str, Any]:
        return {
            "vector": list(self.vector),
            "score": round(self.score, 12),
            "stderr": round(self.stderr, 12),
            "games": self.games,
            "stream": self.stream,
        }


@dataclass(frozen=True)
class Evaluation:
    step: int
    estimate: Estimate
    cumulative_games: int
    tag: str = ""
    """Optimizer-supplied label, e.g. "incumbent", "candidate", "restart"."""

    def as_row(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "cumulative_games": self.cumulative_games,
            "tag": self.tag,
            **self.estimate.as_row(),
        }


@dataclass
class Trace:
    problem: str
    optimizer: str
    seed: int
    budget: int
    config: Mapping[str, Any] = field(default_factory=dict)
    evaluations: list[Evaluation] = field(default_factory=list)

    def record(self, estimate: Estimate, cumulative_games: int, tag: str = "") -> None:
        self.evaluations.append(
            Evaluation(len(self.evaluations), estimate, cumulative_games, tag)
        )

    def __len__(self) -> int:
        return len(self.evaluations)

    def __iter__(self) -> Iterator[Evaluation]:
        return iter(self.evaluations)

    @property
    def games_spent(self) -> int:
        return self.evaluations[-1].cumulative_games if self.evaluations else 0

    @property
    def best(self) -> Estimate | None:
        """Highest-scoring estimate seen.

        This is the *in-sample* winner and is biased upward by selection — the
        winner's curse. Never report it as the optimizer's score without a
        held-out re-evaluation (Phase 6).
        """
        if not self.evaluations:
            return None
        return max((e.estimate for e in self.evaluations), key=lambda e: e.score)

    def best_by(self, key) -> Estimate | None:
        if not self.evaluations:
            return None
        return max((e.estimate for e in self.evaluations), key=key)

    def incumbent_curve(self) -> list[tuple[int, float]]:
        """(cumulative_games, best-so-far score). The anytime performance curve."""
        out: list[tuple[int, float]] = []
        best = float("-inf")
        for ev in self.evaluations:
            best = max(best, ev.estimate.score)
            out.append((ev.cumulative_games, best))
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "problem": self.problem,
            "optimizer": self.optimizer,
            "seed": self.seed,
            "budget": self.budget,
            "config": _canonical(self.config),
            "evaluations": [e.as_row() for e in self.evaluations],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        """Stable hash of the whole run. The reproducibility gate."""
        return hashlib.sha256(self.to_json().encode()).hexdigest()


def _canonical(obj: Any) -> Any:
    """JSON-safe, deterministically ordered. Configs hold tuples and floats that
    would otherwise serialize inconsistently across runs."""
    if isinstance(obj, Mapping):
        return {str(k): _canonical(v) for k, v in sorted(obj.items())}
    if isinstance(obj, (list, tuple)):
        return [_canonical(v) for v in obj]
    if isinstance(obj, float):
        return round(obj, 12)
    if isinstance(obj, (str, int, bool)) or obj is None:
        return obj
    return str(obj)
