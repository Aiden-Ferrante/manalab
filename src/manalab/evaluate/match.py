"""Win rate against a fixed gauntlet, measured by the rules engine.

This is the first evaluator that returns something shaped like "is this deck
good" rather than "is this deck consistent". It is also the first one whose
number can be confidently wrong, so read this before trusting it:

**The pilot is the measurement instrument.** Both seats are played by the same
crude agent. That makes the comparison between two candidate decks fair — they
face identical opposition piloted identically — but it does *not* make the
number a measure of the deck's strength in real play. A search maximising this
will find decks that beat `CurveAgent`, and the gap between that and "good
decks" is exactly the gap between the agent and a real player.

**The gauntlet is the world.** A deck is only ever judged against these
opponents. Win rate against a fixed set is a *relative* quantity; a candidate
that beats every gauntlet deck may simply be well-angled against five decks.
`holdout` exists so that claim can be checked rather than assumed.

**Draws count as half.** The engine stops at a turn limit, and stalled boards
are common in creature mirrors. Scoring a draw as a loss would quietly reward
decks that race and punish decks that grind, which is an opinion about Magic
smuggled in as an implementation detail. `decisive_rate` reports how often it
mattered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from manalab.cards.model import Card, Decklist
from manalab.engine import fidelity
from manalab.engine.agents import Agent, CurveAgent
from manalab.engine.game import Game
from manalab.engine.state import GameState
from manalab.evaluate.result import EvalResult

DEFAULT_MAX_TURNS = 30


@dataclass(frozen=True)
class GauntletDeck:
    """One fixed opponent, pre-resolved to cards so workers need no database."""

    name: str
    cards: tuple[Card, ...]

    @property
    def size(self) -> int:
        return len(self.cards)


@dataclass(frozen=True)
class MatchEvaluator:
    """Plays a candidate against every gauntlet deck and reports the win rate.

    Deliberately holds no database handle: it carries resolved `Card` objects so
    the whole evaluator pickles cleanly to a worker process. A duckdb connection
    here would make the parallel fan-out impossible and the failure would look
    like an unrelated serialisation error.
    """

    gauntlet: tuple[GauntletDeck, ...]
    cards: Mapping[str, Card]
    """Name -> Card, covering every card the candidate pool can name."""

    max_turns: int = DEFAULT_MAX_TURNS
    pilot: Agent = field(default_factory=CurveAgent)
    name: str = "engine-gauntlet"

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(d.name for d in self.gauntlet)

    def resolve(self, deck: Decklist) -> list[Card]:
        """Expand a decklist into the 60 card objects it stands for."""
        out: list[Card] = []
        for card_name, count in deck.counts.items():
            card = self.cards.get(card_name)
            if card is None:
                raise KeyError(f"card not in evaluator pool: {card_name!r}")
            out.extend([card] * count)
        return out

    def evaluate(self, deck: Decklist, *, n_games: int, seed: int) -> EvalResult:
        """Play `n_games`, where game *i* is entirely determined by `seed + i`.

        That indexing is a contract, not a convenience. `search.Oracle` buys
        extra precision on a deck it has already measured by calling again at
        `seed + k`, and expects to receive games *k* onward of the very same
        stream. An evaluator that hashed its seeds would return fresh games
        instead, and every racing and halving procedure above it would quietly
        double-count while believing it had more evidence than it did.

        The opponent and the play/draw assignment are therefore derived from the
        absolute game index too — so a slice of the stream carries its own
        balanced schedule rather than depending on where the loop started.
        """
        candidate = self.resolve(deck)
        n_opponents = len(self.gauntlet)

        results: list[float] = []
        per_opponent: dict[str, list[float]] = {name: [] for name in self.names}
        decisive: list[float] = []
        turns: list[float] = []
        unmodeled: dict[str, tuple[str, ...]] = {}

        for game in range(n_games):
            index = seed + game
            opponent = self.gauntlet[index % n_opponents]
            # Alternate the play only once the whole gauntlet has been faced, so
            # any window of `2 * n_opponents` games is balanced on both axes.
            on_the_play = (index // n_opponents) % 2 == 0

            score, decided, length, blind = self._play(
                candidate, opponent, index, on_the_play
            )
            results.append(score)
            per_opponent[opponent.name].append(score)
            decisive.append(1.0 if decided else 0.0)
            turns.append(float(length))
            for card_name, reason in blind.items():
                unmodeled.setdefault(card_name, (reason,))

        metrics: dict[str, float] = {
            "win_rate": _mean(results),
            "decisive_rate": _mean(decisive),
            "avg_turns": _mean(turns),
        }
        for opponent_name, scores in per_opponent.items():
            if scores:
                metrics[f"vs:{opponent_name}"] = _mean(scores)

        samples: dict[str, tuple[float, ...]] = {
            "win_rate": tuple(results),
            "decisive_rate": tuple(decisive),
            "avg_turns": tuple(turns),
        }

        return EvalResult(
            deck_name=deck.name,
            evaluator=self.name,
            n_games=len(results),
            seed=seed,
            metrics=metrics,
            samples=samples,
            unmodeled=unmodeled,
        )

    def _play(
        self,
        candidate: Sequence[Card],
        opponent: GauntletDeck,
        seed: int,
        on_the_play: bool,
    ) -> tuple[float, bool, int, dict[str, str]]:
        """One game. Returns (score for the candidate, decisive, turns, blind spots).

        The candidate alternates between the play and the draw. Skipping that
        costs roughly seven points of win rate in a mirror, which is larger than
        most of the differences a deck search is trying to detect.
        """
        seats: list[list[Card]] = (
            [list(candidate), list(opponent.cards)]
            if on_the_play
            else [list(opponent.cards), list(candidate)]
        )
        our_seat = 0 if on_the_play else 1

        state = GameState.new(seats, seed=seed)
        game = Game(state, [self.pilot, self.pilot], max_turns=self.max_turns)
        result = game.run()

        if result.winner is None:
            score = 0.5
        else:
            score = 1.0 if result.winner == our_seat else 0.0
        return score, result.decisive, result.turns, result.unmodeled


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def gauntlet_fidelity(gauntlet: Sequence[GauntletDeck]) -> dict[str, tuple[str, ...]]:
    """Blind spots in the gauntlet itself, before a single game is played.

    A gauntlet full of cards the engine ignores is a weak gauntlet in a way no
    win rate will reveal — every candidate beats it, and the search learns
    nothing.
    """
    out: dict[str, tuple[str, ...]] = {}
    for deck in gauntlet:
        for card in set(deck.cards):
            report = fidelity.assess(card)
            if not report.faithful:
                out[card.name] = report.reasons
    return out
