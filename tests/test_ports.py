"""Synergy ports: extraction, the bottleneck score, and the metric injection."""

from __future__ import annotations

from manalab.cards.mana import parse_cost
from manalab.cards.model import Card, Decklist
from manalab.search.objective import THROUGHPUT_SYNERGY
from manalab.search.ports import SynergyEvaluator, ports_of, synergy_score


def card(name: str, text: str, *, keywords=(), cost="{1}") -> Card:
    return Card(oracle_id=name, name=name, cost=parse_cost(cost),
                type_line="Creature — Test", oracle_text=text,
                keywords=frozenset(keywords))


PRODUCER = card("Maker", "Create two 1/1 white Soldier creature tokens.")
OUTLET = card("Outlet", "{T}: Sacrifice a creature. Draw a card.")
PAYOFF = card("Payoff", "Whenever a creature dies, each opponent loses 1 life.")
BLANK = card("Blank", "Draw a card.")


def test_ports_extract_from_structure():
    assert ports_of(PRODUCER)["bodies"] == frozenset({"provides"})
    assert "requires" in ports_of(OUTLET)["bodies"]
    assert "provides" in ports_of(OUTLET)["death_events"]
    assert ports_of(PAYOFF)["death_events"] == frozenset({"requires"})
    assert ports_of(BLANK) == {}


CARDS = {c.name: c for c in (PRODUCER, OUTLET, PAYOFF, BLANK)}


def test_score_is_a_bottleneck_not_a_sum():
    """Ten producers with one outlet close one pair, not ten."""
    lopsided = Decklist({"Maker": 4, "Outlet": 1})
    # bodies min(4,1)=1; death_events has a provider but no consumer here, so 0.
    assert synergy_score(lopsided, CARDS) == 1.0


def test_closing_the_missing_leg_jumps_the_score():
    """Supermodularity where the frame says synergy lives: the payoff is worth
    nothing alone and something in company."""
    without = synergy_score(Decklist({"Maker": 2, "Outlet": 2}), CARDS)
    with_payoff = synergy_score(Decklist({"Maker": 2, "Outlet": 2, "Payoff": 2}), CARDS)
    alone = synergy_score(Decklist({"Payoff": 2}), CARDS)
    assert alone == 0.0
    assert with_payoff > without, "the added leg closes death_event pairs"


def test_blanks_contribute_nothing():
    assert synergy_score(Decklist({"Blank": 4}), CARDS) == 0.0


def test_the_wrapper_injects_a_constant_metric():
    class Probe:
        def evaluate(self, deck, *, n_games, seed):
            from manalab.evaluate.result import EvalResult
            return EvalResult(deck_name="d", evaluator="probe", n_games=n_games,
                              seed=seed, metrics={"mana_spent": 10.0},
                              samples={"mana_spent": (10.0,) * n_games})

    wrapped = SynergyEvaluator(inner=Probe(), cards=CARDS)
    result = wrapped.evaluate(Decklist({"Maker": 2, "Outlet": 2}), n_games=5, seed=3)
    assert result.metrics["synergy"] == 2.0    # bodies min(2,2); death has no taker
    assert result.samples["synergy"] == (2.0,) * 5
    assert result.stderr("synergy") == 0.0, "a structural prior has no noise"
    # and the rung's objective consumes it with no special cases
    assert THROUGHPUT_SYNERGY(result) == 10.0 + 0.5 * 2.0


def test_without_the_wrapper_the_rung_collapses_to_throughput():
    from manalab.evaluate.result import EvalResult
    bare = EvalResult(deck_name="d", evaluator="probe", n_games=5, seed=3,
                      metrics={"mana_spent": 10.0})
    assert THROUGHPUT_SYNERGY(bare) == 10.0
