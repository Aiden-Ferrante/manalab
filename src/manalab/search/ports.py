"""Synergy ports as an objective term — the census promoted to library code.

docs/synergy-ports.md defined the ports; the census proved every one is
two-sided on the real corpus. This module turns the structure into a number an
objective can carry:

    synergy_score(deck) = Σ over ports of min(provider copies, consumer copies)

The min is a bottleneck reading — a port is worth the pairs it can actually
close, so ten token producers with one sacrifice outlet score 1, not 10. It is
supermodular exactly where the frame says synergy lives: adding the missing leg
of a chain jumps the score, adding a redundant leg moves it not at all.

The score enters evaluation as an injected *metric*. The `Objective` protocol is
`EvalResult → float` and never sees the deck, so `SynergyEvaluator` computes the
score at evaluate time and writes it into the result as a constant per-game
sample — every downstream statistic (racing, CIs, CRN pairing) works unchanged,
and the synergy term contributes exactly zero simulation variance, which is
true: it is a structural prior, not a measurement.

What the weights are NOT, stated plainly: measured value. How much a closed
pair is worth in wins is an engine question. The objective's λ is a declared
modelling assumption to be calibrated when an evaluator that can see synergy
exists — until then it is visible, adjustable, and honest about being a prior.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Mapping

from manalab.cards.effects import parse_card
from manalab.cards.model import Card, Decklist
from manalab.evaluate.result import EvalResult, Evaluator

GRAVE_KEYWORDS = {"flashback", "escape", "unearth", "embalm", "eternalize",
                  "scavenge", "delve", "disturb", "jump-start", "aftermath"}
_DIES = re.compile(r"\bdies\b|put into a graveyard from the battlefield", re.I)
_GAINS_LIFE = re.compile(r"\bgains? life\b|\byou gain life\b", re.I)
_COUNTER_ON = re.compile(r"counters? (?:is|are) put on|put a [^ ]+ counter", re.I)
_OWN_SAC = re.compile(
    r"^(a|an|another|any number of)? ?(creature|permanent|artifact|token)s?\b", re.I)

_CACHE: dict[str, dict[str, frozenset[str]]] = {}


def ports_of(card: Card) -> dict[str, frozenset[str]]:
    """port → roles ('provides' / 'requires'), from parsed structure. Cached —
    a card's ports never change within a process."""
    cached = _CACHE.get(card.oracle_id)
    if cached is not None:
        return cached

    parsed = parse_card(card)
    out: dict[str, set[str]] = defaultdict(set)
    kw = {k.lower() for k in card.keywords}

    for ability in parsed.abilities:
        if "sacrifice" in ability.cost.lower():
            out["bodies"].add("requires")
            out["death_events"].add("provides")
        if ability.trigger:
            if _DIES.search(ability.trigger):
                out["death_events"].add("requires")
            if _GAINS_LIFE.search(ability.trigger):
                out["life_events"].add("requires")
            if _COUNTER_ON.search(ability.trigger):
                out["counters"].add("requires")

    for effect in parsed.effects:
        params = dict(effect.params)
        if effect.verb == "create_token":
            out["bodies"].add("provides")
        elif effect.verb == "sacrifice":
            if _OWN_SAC.match(str(params.get("what", "")).strip()):
                out["bodies"].add("requires")
                out["death_events"].add("provides")
        elif effect.verb == "put_counters" and "+1/+1" in str(params.get("kind", "")):
            out["counters"].add("provides")
        elif effect.verb == "proliferate":
            out["counters"].add("requires")
        elif effect.verb in ("mill", "discard"):
            out["graveyard"].add("provides")
        elif effect.verb == "return_from_graveyard":
            out["graveyard"].add("requires")
        elif effect.verb == "gain_life":
            out["life_events"].add("provides")

    if kw & GRAVE_KEYWORDS:
        out["graveyard"].add("requires")

    frozen = {port: frozenset(roles) for port, roles in out.items()}
    _CACHE[card.oracle_id] = frozen
    return frozen


def port_profile(deck: Decklist,
                 cards: Mapping[str, Card]) -> dict[tuple[str, str], int]:
    """(port, role) → copies. Cards missing from `cards` contribute nothing —
    absence of data is not evidence of absence of ports, but it is all we have."""
    profile: dict[tuple[str, str], int] = defaultdict(int)
    for name, copies in deck.counts.items():
        card = cards.get(name)
        if card is None:
            continue
        for port, roles in ports_of(card).items():
            for role in roles:
                profile[(port, role)] += copies
    return dict(profile)


def synergy_score(deck: Decklist, cards: Mapping[str, Card]) -> float:
    """Closable pairs across all ports: Σ min(provides, requires), in copies."""
    profile = port_profile(deck, cards)
    ports = {p for p, _ in profile}
    return float(sum(min(profile.get((p, "provides"), 0),
                         profile.get((p, "requires"), 0)) for p in ports))


@dataclass(frozen=True)
class SynergyEvaluator:
    """Injects `synergy` as a metric so any LinearObjective can weight it.

    Wraps the seam like FittedEvaluator does: the inner evaluator is untouched,
    CRN seeds pass through, and the injected samples are constant per game —
    zero added variance, which is the honest amount for a structural prior.
    """

    inner: Evaluator
    cards: Mapping[str, Card]
    name: str = "synergy-injected"

    def evaluate(self, deck: Decklist, *, n_games: int, seed: int) -> EvalResult:
        result = self.inner.evaluate(deck, n_games=n_games, seed=seed)
        score = synergy_score(deck, self.cards)
        return replace(
            result,
            metrics={**result.metrics, "synergy": score},
            samples={**result.samples, "synergy": (score,) * result.n_games},
        )
