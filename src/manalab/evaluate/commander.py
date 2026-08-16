"""Four-seat Commander games as an evaluator: a decklist in, a win share out.

The rest of the machinery existed — multiplayer combat, the command zone, the
tax, 21 commander damage, singleton pools via `formats.COMMANDER` — and nothing
assembled it into the `evaluate(deck, n_games, seed) -> EvalResult` seam that
search speaks. This is that assembly, and deliberately nothing more.

Scope, stated the way ARCHITECTURE.md demands: every seat is piloted by the
same crude `CurveAgent`, so the number measures "wins this four-seat table
under this pilot", not deck strength — and in multiplayer that caveat is
*heavier* than in 1v1, because the pilot has no politics: it attacks the next
living opponent's face and never reasons about threat. Reported with that
attached, or not reported.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from manalab.cards.model import Card, Decklist
from manalab.engine.agents import CurveAgent
from manalab.engine.game import Game
from manalab.engine.state import GameState
from manalab.engine.zones import Zone
from manalab.evaluate.result import EvalResult

STARTING_LIFE = 40
MAX_TURNS = 24


@dataclass(frozen=True)
class CommanderDeck:
    """A 99-card library plus the commander that starts in the command zone."""

    name: str
    commander: Card
    library: tuple[Card, ...]


def resolve_deck(deck: Decklist, commander_name: str,
                 cards: Mapping[str, Card], name: str = "") -> CommanderDeck:
    """A decklist (commander included) into a playable CommanderDeck."""
    library: list[Card] = []
    commander: Card | None = None
    for card_name, count in deck.counts.items():
        card = cards[card_name]
        if card_name == commander_name:
            commander = card
            count -= 1
        library.extend([card] * count)
    if commander is None:
        raise ValueError(f"{commander_name!r} is not in the deck")
    return CommanderDeck(name or deck.name, commander, tuple(library))


class CommanderEvaluator:
    """Win share of a candidate deck at a table of three fixed opponents.

    Honours the game-*i*-at-seed-*s+i* contract the `Oracle` splices on. The
    candidate's seat rotates with the game index, so no deck owns the play-first
    advantage across a stream.
    """

    def __init__(self, gauntlet: Sequence[CommanderDeck], *,
                 candidate_name: str = "candidate") -> None:
        if len(gauntlet) != 3:
            raise ValueError("a Commander table wants exactly three opponents")
        self.gauntlet = tuple(gauntlet)
        self.candidate_name = candidate_name
        self.evaluator = "commander"

    def evaluate(self, deck: CommanderDeck, *, n_games: int, seed: int) -> EvalResult:
        wins: list[float] = []
        lengths: list[float] = []
        for i in range(n_games):
            won, turns = self._one_game(deck, seed + i)
            wins.append(won)
            lengths.append(turns)
        return EvalResult(
            deck_name=deck.name,
            evaluator=self.evaluator,
            n_games=n_games,
            seed=seed,
            metrics={"win_rate": sum(wins) / max(len(wins), 1),
                     "game_length": sum(lengths) / max(len(lengths), 1)},
            samples={"win_rate": tuple(wins), "game_length": tuple(lengths)},
        )

    def _one_game(self, deck: CommanderDeck, game_seed: int) -> tuple[float, float]:
        seat = game_seed % 4
        seats: list[CommanderDeck] = list(self.gauntlet)
        seats.insert(seat, deck)

        state = GameState.new([d.library for d in seats], seed=game_seed,
                              names=[d.name for d in seats],
                              starting_life=STARTING_LIFE)
        for index, seated in enumerate(seats):
            state.shuffle(index)
            general = state.create(seated.commander, owner=index,
                                   zone=Zone.COMMAND, quiet=True)
            general.is_commander = True

        game = Game(state, [CurveAgent() for _ in seats], max_turns=MAX_TURNS)
        game.setup()
        result = game.run()
        won = 1.0 if result.winner == seat else 0.0
        return won, float(state.turn)
