"""Consistency evaluator: the goldfish sim behind the `Evaluator` protocol.

Measures whether a deck does what it's built to do — hit land drops, curve out,
have the right colors on time. It cannot measure whether a deck wins, because
there is no opponent. That limitation is the honest version of v1.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from manalab.cards.model import Card, Decklist
from manalab.evaluate.result import EvalResult
from manalab.game import goldfish
from manalab.game.library import resolve
from manalab.game.mulligan import BottomPolicy, KeepPolicy


@dataclass
class ConsistencyEvaluator:
    """Runs N goldfish games and summarises them.

    `targets` are the questions you actually care about: `[("Wrath of God", 4)]`
    asks "how often is Wrath castable on turn four", surfacing as the metric
    `castable_wrath_of_god_by_t4`. This is where a vague notion of "good mana
    base" becomes a number a search loop can maximise.

    Each target also emits `cast_<name>_by_t<n>`, which is how often it was
    actually cast. That number is lower and depends on the play policy — two
    one-drops compete for the same first land. Optimise against `castable_*`
    unless you specifically mean to include the policy's choices.
    """

    cards: Mapping[str, Card]
    turns: int = goldfish.DEFAULT_TURNS
    on_the_play: bool = True
    targets: Sequence[tuple[str, int]] = ()
    curve_turns: Sequence[int] = (2, 3, 4, 5)
    keep: KeepPolicy | None = None
    bottom: BottomPolicy | None = None
    name: str = "consistency-goldfish-v1"

    def evaluate(self, deck: Decklist, *, n_games: int, seed: int) -> EvalResult:
        library = resolve(deck, self.cards)

        samples: dict[str, list[float]] = {}

        def record(key: str, value: float) -> None:
            samples.setdefault(key, []).append(value)

        for i in range(n_games):
            # Seeds are derived, not drawn: evaluating two decks with the same
            # `seed` gives them the same shuffle stream. That pairing is worth
            # roughly an order of magnitude in samples when comparing decks.
            game = goldfish.play(
                library,
                seed=seed + i,
                turns=self.turns,
                on_the_play=self.on_the_play,
                keep=self.keep,
                bottom=self.bottom,
            )

            record("mulligans", game.mulligans)
            record("kept_hand", float(game.mulligans == 0))
            record("missed_land_drops", game.missed_land_drops)
            record("mana_spent", game.total_mana_spent)

            for t in self.curve_turns:
                record(f"p_on_curve_t{t}", float(game.on_curve_through(t)))
                if t <= len(game.mana_available):
                    record(f"mana_t{t}", game.mana_available[t - 1])

            for card_name, turn in self.targets:
                slug = _slug(card_name)
                record(f"castable_{slug}_by_t{turn}", float(game.castable_by(card_name, turn)))
                record(f"cast_{slug}_by_t{turn}", float(game.cast_by(card_name, turn)))

        metrics = {k: statistics.fmean(v) for k, v in samples.items()}

        unmodeled = {
            name: tuple(reasons)
            for name, reasons in goldfish.scan_unmodeled(library).items()
        }

        return EvalResult(
            deck_name=deck.name,
            evaluator=self.name,
            n_games=n_games,
            seed=seed,
            metrics=metrics,
            samples={k: tuple(v) for k, v in samples.items()},
            unmodeled=unmodeled,
        )


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")
