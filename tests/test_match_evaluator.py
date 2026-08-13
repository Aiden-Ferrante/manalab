"""The gauntlet evaluator, the fidelity predicate, and the pool split.

The seed-contract tests here are the load-bearing ones. `search.Oracle` buys
extra precision by calling an evaluator again at a later seed and splicing the
results onto what it already has; if that splice is wrong the search layer
double-counts games while believing it has more evidence than it does, and
nothing downstream can detect it.
"""

from __future__ import annotations

import pytest

from manalab.cards.mana import parse_cost
from manalab.cards.model import Card, Decklist
from manalab.engine import fidelity
from manalab.evaluate import gauntlet as G
from manalab.evaluate import pool as P
from manalab.evaluate.match import GauntletDeck, MatchEvaluator, gauntlet_fidelity

FOREST = Card("forest", "Forest", parse_cost(None), "Basic Land — Forest",
              produces=frozenset("G"), taps_for_mana=True, oracle_text="")
BEAR = Card("bear", "Bear", parse_cost("{1}{G}"), "Creature — Bear",
            power="2", toughness="2")
GIANT = Card("giant", "Giant", parse_cost("{4}{G}"), "Creature — Giant",
             power="5", toughness="5")
FLYER = Card("flyer", "Flyer", parse_cost("{2}{G}"), "Creature — Bird",
             power="2", toughness="2", keywords=frozenset({"Flying"}),
             oracle_text="Flying")
WEIRD = Card("weird", "Weird", parse_cost("{1}{G}"), "Creature — Weird",
             power="2", toughness="2", oracle_text="When this dies, draw a card.")
BOLT = Card("bolt", "Bolt", parse_cost("{R}"), "Instant",
            oracle_text="Bolt deals 3 damage to any target.")
ECHO = Card("echo", "Echo", parse_cost("{1}{G}"), "Creature — Elk",
            power="2", toughness="2", keywords=frozenset({"Echo"}),
            oracle_text="Echo {1}{G}")


def deck_of(*pairs: tuple[Card, int]) -> tuple[Card, ...]:
    out: list[Card] = []
    for card, n in pairs:
        out.extend([card] * n)
    return tuple(out)


AGGRO = GauntletDeck("aggro", deck_of((FOREST, 24), (BEAR, 36)))
BIG = GauntletDeck("big", deck_of((FOREST, 26), (GIANT, 34)))


def evaluator(*decks: GauntletDeck) -> MatchEvaluator:
    return MatchEvaluator(
        gauntlet=decks or (AGGRO, BIG),
        cards={c.name: c for c in (FOREST, BEAR, GIANT, FLYER)},
    )


def candidate() -> Decklist:
    return Decklist({"Forest": 24, "Bear": 36}, "candidate")


# --- fidelity -----------------------------------------------------------


def test_a_vanilla_creature_is_faithful() -> None:
    assert fidelity.assess(BEAR).faithful


def test_a_creature_whose_only_text_is_an_implemented_keyword_is_faithful() -> None:
    assert fidelity.assess(FLYER).faithful


def test_a_basic_land_is_faithful() -> None:
    assert fidelity.assess(FOREST).faithful


def test_rules_text_makes_a_card_unfaithful() -> None:
    report = fidelity.assess(WEIRD)
    assert not report.faithful
    assert any("does not execute" in r for r in report.reasons)


def test_an_unimplemented_keyword_makes_a_card_unfaithful() -> None:
    report = fidelity.assess(ECHO)
    assert not report.faithful
    assert any("echo" in r.lower() for r in report.reasons)


def test_an_instant_with_no_parsed_effects_is_unfaithful() -> None:
    """BOLT here is hand-built with oracle text but no parsed `Effect`s.

    Instants are no longer inert as a class — `engine.resolve` executes damage,
    destroy, draw, gain-life and pump. What is refused now is a specific card the
    engine cannot execute, which is a much narrower and more useful claim.
    """
    report = fidelity.assess(BOLT)
    assert not report.faithful
    assert any("no parsed effects" in r for r in report.reasons)


def test_a_real_burn_spell_is_now_faithful() -> None:
    from manalab.cards.store import CardStore

    bolt = CardStore().by_name("Lightning Bolt")
    assert fidelity.assess(bolt).faithful, fidelity.assess(bolt).reasons


def test_a_counterspell_is_now_faithful() -> None:
    from manalab.cards.store import CardStore

    assert fidelity.assess(CardStore().by_name("Counterspell")).faithful


def test_a_token_maker_is_still_refused() -> None:
    from manalab.cards.store import CardStore

    report = fidelity.assess(CardStore().by_name("Raise the Alarm"))
    assert not report.faithful
    assert any("create_token" in r for r in report.reasons)


def test_every_combat_keyword_is_actually_implemented() -> None:
    """Guards the drift this module exists to prevent.

    If a keyword is listed as implemented here but `engine.combat` never reads
    it, cards get admitted to the faithful pool on a false promise.
    """
    import inspect

    from manalab.engine import combat, objects

    source = inspect.getsource(combat) + inspect.getsource(objects)
    for keyword in fidelity.COMBAT_KEYWORDS:
        assert keyword.title() in source or keyword.capitalize() in source, (
            f"{keyword!r} is claimed as implemented but never read by the engine"
        )


# --- the pool split -----------------------------------------------------


def test_partition_splits_faithful_from_text() -> None:
    pool = P.partition([BEAR, FLYER, WEIRD, BOLT, FOREST], unlimited={"Forest"})
    assert set(pool.cards) == {"Bear", "Flyer", "Forest"}
    assert {c.name for c in pool.text_tier} == {"Weird", "Bolt"}


def test_the_text_tier_records_why() -> None:
    pool = P.partition([BEAR, WEIRD])
    assert pool.why("Weird")
    assert pool.why("Bear") == ()


def test_basics_are_capped_by_deck_size_not_the_four_copy_rule() -> None:
    pool = P.partition([BEAR, FOREST], deck_size=60, unlimited={"Forest"})
    assert pool.pool.limit("Forest") == 60
    assert pool.pool.limit("Bear") == 4


def test_gaps_ranks_the_commonest_reason_first() -> None:
    pool = P.partition([WEIRD, BOLT, ECHO])
    assert pool.gaps()[0][1] >= pool.gaps()[-1][1]


# --- the seed contract --------------------------------------------------


def test_evaluation_is_reproducible() -> None:
    a = evaluator().evaluate(candidate(), n_games=20, seed=7)
    b = evaluator().evaluate(candidate(), n_games=20, seed=7)
    assert a.samples["win_rate"] == b.samples["win_rate"]


def test_game_i_at_seed_s_equals_game_0_at_seed_s_plus_i() -> None:
    """The property `search.Oracle` splices on. Break it and racing breaks."""
    whole = evaluator().evaluate(candidate(), n_games=12, seed=100)
    for offset in range(12):
        one = evaluator().evaluate(candidate(), n_games=1, seed=100 + offset)
        assert one.samples["win_rate"][0] == whole.samples["win_rate"][offset], (
            f"game {offset} of the stream is not reproducible on its own"
        )


def test_a_later_call_continues_the_same_stream() -> None:
    """Exactly how the oracle buys more precision on a deck it already has."""
    whole = evaluator().evaluate(candidate(), n_games=20, seed=50)
    first = evaluator().evaluate(candidate(), n_games=8, seed=50)
    rest = evaluator().evaluate(candidate(), n_games=12, seed=58)

    spliced = first.samples["win_rate"] + rest.samples["win_rate"]
    assert spliced == whole.samples["win_rate"]


def test_different_seeds_give_different_games() -> None:
    a = evaluator().evaluate(candidate(), n_games=40, seed=1)
    b = evaluator().evaluate(candidate(), n_games=40, seed=9_000)
    assert a.samples["win_rate"] != b.samples["win_rate"]


# --- what the numbers mean ----------------------------------------------


def test_every_opponent_is_faced() -> None:
    result = evaluator().evaluate(candidate(), n_games=40, seed=0)
    assert result.metrics["vs:aggro"] is not None
    assert result.metrics["vs:big"] is not None


def test_the_schedule_is_balanced_on_play_and_draw() -> None:
    """A window of 2 * gauntlet size must contain each seat once per opponent."""
    ev = evaluator()
    seen: list[tuple[str, bool]] = []
    for game in range(4):
        index = 0 + game
        opponent = ev.gauntlet[index % len(ev.gauntlet)]
        on_the_play = (index // len(ev.gauntlet)) % 2 == 0
        seen.append((opponent.name, on_the_play))
    assert sorted(seen) == sorted(
        [("aggro", True), ("big", True), ("aggro", False), ("big", False)]
    )


def test_win_rate_is_bounded_and_samples_match_the_mean() -> None:
    result = evaluator().evaluate(candidate(), n_games=20, seed=3)
    xs = result.samples["win_rate"]
    assert all(x in (0.0, 0.5, 1.0) for x in xs)
    assert result.metrics["win_rate"] == pytest.approx(sum(xs) / len(xs))


def test_a_mirror_is_a_coin_flip() -> None:
    """Same deck both seats, balanced play/draw — anything far from 0.5 is a bug."""
    ev = evaluator(AGGRO)
    result = ev.evaluate(Decklist({"Forest": 24, "Bear": 36}), n_games=200, seed=11)
    assert result.metrics["win_rate"] == pytest.approx(0.5, abs=0.12)


def test_an_unknown_card_is_refused_rather_than_ignored() -> None:
    with pytest.raises(KeyError):
        evaluator().evaluate(Decklist({"Nonesuch": 60}), n_games=1, seed=0)


def test_gauntlet_fidelity_reports_a_weak_gauntlet() -> None:
    dirty = GauntletDeck("dirty", deck_of((FOREST, 24), (WEIRD, 36)))
    assert "Weird" in gauntlet_fidelity([dirty])
    assert gauntlet_fidelity([AGGRO]) == {}


# --- the built gauntlet -------------------------------------------------


def test_built_decks_are_legal_sixty_card_decks() -> None:
    pool = P.partition([FOREST, BEAR, GIANT, FLYER], unlimited={"Forest"})
    for deck in G.standard(pool):
        assert deck.size == 60


def test_zero_toughness_creatures_never_reach_a_gauntlet_deck() -> None:
    """They die to state-based actions on resolution — a free win for any search."""
    doomed = Card("doomed", "Doomed", parse_cost("{G}"), "Creature — Horror",
                  power="8", toughness="0")
    pool = P.partition([FOREST, BEAR, doomed], unlimited={"Forest"})
    for deck in G.standard(pool):
        assert "Doomed" not in {c.name for c in deck.cards}


def test_legendary_cards_are_set_aside() -> None:
    """No legend rule in the engine, so extra copies stack and search abuses it."""
    legend = Card("l", "Legend", parse_cost("{2}{G}"), "Legendary Creature — Elk",
                  power="9", toughness="7")
    report = fidelity.assess(legend)
    assert not report.faithful
    assert any("legend" in r.lower() for r in report.reasons)
