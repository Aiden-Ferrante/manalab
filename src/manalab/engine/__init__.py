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
  combat .... blocking legality and damage assignment, with keywords
  targets ... the target language, and enumerating legal choices
  resolve ... effect verbs: what a spell does when it resolves
  agents .... Agent protocol plus passing/random/curve baselines
  game ...... the driver: turns, priority, the stack, combat
  fidelity .. what the engine can and cannot represent, asked of a card

Combat keywords implemented: flying, reach, menace, trample, deathtouch, first
strike, double strike, lifelink, vigilance, haste, defender.

Effect verbs implemented: deal_damage, destroy, draw, gain_life, pump — each
resolving against targets chosen on announcement and re-checked on resolution.

`fidelity` is the single source of truth for both lists and derives them from
`COMBAT_KEYWORDS` and `resolve.IMPLEMENTED` rather than restating them. Check a
claim against those, never against this docstring.

Not yet: triggered and activated abilities, counterspells, continuous effects
(a pump is modelled as counters, so it does not wear off), flash, protection and
hexproof, the legend rule, damage-assignment order chosen by the attacker.
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
