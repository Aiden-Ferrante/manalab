"""Phase 7 — interpretation. Turning replicated runs into claims you can defend.

A genetic algorithm is a stochastic process, so one run is one sample. This
module exists because that fact was ignored for a whole session: a five-colour
tournament was rerun after each engine change and the shifting spread narrated
as an effect, until replication showed the seed-to-seed noise (±0.116) was wider
than every "effect" being reported (≤0.13).

The rule this encodes: **do not print a ranking you cannot separate.** Means go
out with their uncertainty, and labels whose difference is inside the noise are
shown as one tier rather than as an order. An ordering is a much stronger claim
than a measurement, and it is the one readers remember.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

__all__ = ["Measurement", "distinguishable", "summarise", "table", "tiers"]


@dataclass(frozen=True)
class Measurement:
    """One label measured over several independent runs."""

    label: str
    samples: tuple[float, ...]

    @property
    def n(self) -> int:
        return len(self.samples)

    @property
    def mean(self) -> float:
        return statistics.fmean(self.samples) if self.samples else 0.0

    @property
    def sd(self) -> float:
        """Spread across runs — how much the answer moves when only the seed does."""
        return statistics.stdev(self.samples) if self.n > 1 else 0.0

    @property
    def stderr(self) -> float:
        return self.sd / (self.n**0.5) if self.n > 1 else 0.0

    @property
    def ci95(self) -> tuple[float, float]:
        margin = 1.96 * self.stderr
        return (self.mean - margin, self.mean + margin)


def summarise(runs: Mapping[str, Sequence[float]]) -> list[Measurement]:
    """`{label: [score per seed]}` -> measurements, best mean first."""
    out = [Measurement(label, tuple(samples)) for label, samples in runs.items()]
    return sorted(out, key=lambda m: -m.mean)


def distinguishable(a: Measurement, b: Measurement, *, sigmas: float = 2.0) -> bool:
    """Whether two means are further apart than the noise in their difference.

    Uses the standard error of the *difference*, not either measurement's own —
    comparing a gap against a single standard deviation is the usual way two
    overlapping results get reported as an ordering.
    """
    noise = (a.stderr**2 + b.stderr**2) ** 0.5
    if noise == 0.0:
        return a.mean != b.mean
    return abs(a.mean - b.mean) > sigmas * noise


def tiers(
    measurements: Iterable[Measurement], *, sigmas: float = 2.0
) -> list[list[Measurement]]:
    """Group into bands that cannot be told apart.

    A label joins the current tier unless it is distinguishable from *every*
    member of it — so a tier is a set of results the data does not order.
    """
    ordered = sorted(measurements, key=lambda m: -m.mean)
    grouped: list[list[Measurement]] = []

    for measurement in ordered:
        if grouped and not all(
            distinguishable(measurement, other, sigmas=sigmas)
            for other in grouped[-1]
        ):
            grouped[-1].append(measurement)
        else:
            grouped.append([measurement])
    return grouped


def table(measurements: Sequence[Measurement], *, sigmas: float = 2.0) -> str:
    """A report that shows tiers rather than a false ordering."""
    if not measurements:
        return "(no runs)"

    n = measurements[0].n
    lines = [
        f"{'':<10}{'mean':>8}{'sd':>8}{'95% CI':>18}   runs",
        "-" * 56,
    ]
    for m in sorted(measurements, key=lambda x: -x.mean):
        low, high = m.ci95
        lines.append(
            f"{m.label:<10}{m.mean:>8.3f}{m.sd:>8.3f}"
            f"{f'[{low:.3f}, {high:.3f}]':>18}   {m.n}"
        )

    lines.append("")
    banded = tiers(measurements, sigmas=sigmas)
    if len(banded) == 1:
        lines.append(
            f"No ordering is supported at {sigmas:g} sigma over {n} runs — "
            "every result is inside the noise."
        )
    else:
        lines.append(f"Separable at {sigmas:g} sigma over {n} runs:")
        for index, tier in enumerate(banded, 1):
            names = ", ".join(f"{m.label} {m.mean:.3f}" for m in tier)
            joiner = "  ==  " if len(tier) > 1 else ""
            lines.append(f"  tier {index}: {names}"
                         + ("   (indistinguishable)" if joiner else ""))
    return "\n".join(lines)
