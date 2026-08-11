"""L1 — the rules engine. May import `manalab.cards` and nothing else from manalab.

The long-term home for "the entire game": zones, turn structure, priority, the
stack, two players. Peer to `manalab.game`, not its replacement — that package
answers consistency questions in microseconds, this one answers interaction
questions in milliseconds, and both sit behind the same `Evaluator` protocol.

**Neither may import the other.** See ARCHITECTURE.md.

Grown one effect verb at a time. Cards whose behaviour is not yet implemented are
reported, never silently ignored — a rules engine that quietly does nothing is
far more dangerous than a goldfish sim that advertises its blind spots.

Built so far:
  zones ..... the seven zones, private/shared/ordered/hidden distinctions
  objects ... GameObject: a card plus its current state
  player .... life, land drops, loss conditions
  state ..... GameState, with zone movement as the single mutation primitive
  steps ..... phases, steps, sorcery-speed timing
  sba ....... state-based actions, applied to a fixed point
  mana ...... paying costs by tapping permanents
  actions ... the legal-move vocabulary agents choose from
  agents .... Agent protocol plus passing/random/curve baselines
  game ...... the driver: turns, priority, the stack, combat

Not yet: effect verbs (spells resolve doing nothing and say so), triggered and
activated abilities, first strike, multi-blocks, flash, continuous effects.
"""

from manalab.engine.agents import Agent, CurveAgent, PassingAgent, RandomAgent
from manalab.engine.game import Game, GameResult
from manalab.engine.objects import GameObject
from manalab.engine.player import STARTING_LIFE, Player
from manalab.engine.state import GameState
from manalab.engine.steps import TURN, Phase, Step
from manalab.engine.zones import HIDDEN, ORDERED, PRIVATE, SHARED, Zone

__all__ = [
    "HIDDEN",
    "ORDERED",
    "PRIVATE",
    "SHARED",
    "STARTING_LIFE",
    "TURN",
    "Agent",
    "CurveAgent",
    "Game",
    "GameObject",
    "GameResult",
    "GameState",
    "PassingAgent",
    "Phase",
    "Player",
    "RandomAgent",
    "Step",
    "Zone",
]
