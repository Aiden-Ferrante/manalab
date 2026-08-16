"""Effect-verb parsing.

Uses literal oracle text rather than the card store, so a failure means the
parser changed rather than that Scryfall did.

The governing property is in `test_nothing_is_ever_silently_dropped`: every
clause must land in either `effects` or `unparsed`. A parser that quietly
discards text will report high coverage and produce an engine that plays a
different game from the one on the cards.
"""

from __future__ import annotations

import pytest

from manalab.cards.effects import (
    normalise,
    parse_text,
    quantity,
)


def verbs(text: str, name: str = "CARD", keywords=()) -> list[str]:
    return [e.verb for e in parse_text(text, name, keywords).effects]


def params(text: str, verb: str, name: str = "CARD") -> dict:
    for effect in parse_text(text, name).effects:
        if effect.verb == verb:
            return dict(effect.params)
    raise AssertionError(f"{verb} not found in {verbs(text, name)}")


# --- normalisation ------------------------------------------------------


def test_reminder_text_is_stripped() -> None:
    out = normalise("Flying (This creature can't be blocked except by fliers.)")
    assert "blocked" not in out
    assert out.startswith("Flying")


def test_the_cards_own_name_becomes_a_placeholder() -> None:
    """Self-reference is the only signal distinguishing "this creature gets
    +1/+1" from "target creature gets +1/+1"."""
    assert normalise("Grizzly Bears gets +1/+1", "Grizzly Bears") == "CARDNAME gets +1/+1"


def test_short_names_of_legendary_cards_are_matched() -> None:
    out = normalise("Jace draws a card", "Jace, the Mind Sculptor")
    assert out == "CARDNAME draws a card"


def test_newlines_survive_normalisation() -> None:
    """Newlines separate abilities. Collapsing them merges a keyword line into
    the trigger below it and loses both."""
    out = normalise("Haste\nWhenever this attacks, draw a card.")
    assert "\n" in out


def test_quantity_words_and_variables() -> None:
    assert quantity("3") == 3
    assert quantity("two") == 2
    assert quantity("a") == 1
    # A variable stays itself. It used to become -1 — a number that looks like an
    # answer, which the old test here endorsed while its sibling's docstring said
    # the opposite.
    assert quantity("X") == "X"
    assert quantity("gibberish") == "gibberish"


# --- verbs --------------------------------------------------------------


def test_damage() -> None:
    got = params("CARDNAME deals 3 damage to any target.", "deal_damage")
    assert got == {"amount": 3, "target": "any target"}


def test_draw_and_discard_in_one_clause() -> None:
    """A clause can carry several verbs; keeping only the first loses half the card."""
    assert verbs("Draw a card, then discard a card.") == ["draw", "discard"]


def test_mana_symbols() -> None:
    assert params("{T}: Add {C}{C}.", "add_mana")["mana"].strip() == "{C}{C}"


def test_mana_in_words() -> None:
    assert params("{T}: Add one mana of any color.", "add_mana_any") == {"amount": 1}


def test_counters() -> None:
    got = params("Put two +1/+1 counters on target creature.", "put_counters")
    assert got["amount"] == 2 and got["kind"] == "+1/+1"


def test_scry_and_draw() -> None:
    assert verbs("Scry 1. Draw a card.") == ["scry", "draw"]


def test_destroy_and_rider_are_both_seen() -> None:
    got = verbs("Destroy all creatures. They can't be regenerated.")
    assert "destroy" in got and "cant_be_regenerated" in got


def test_counter_spell_is_matched_before_generic_targets() -> None:
    assert "counter_spell" in verbs("Counter target spell.")


def test_x_costs_produce_a_variable_not_a_number() -> None:
    """A card that draws X cards must not read as drawing -1.

    The old assertion compared against VARIABLE — which *was* -1, so the test
    endorsed exactly what its own docstring forbade."""
    assert params("Draw X cards.", "draw")["amount"] == "X"


# --- ability structure --------------------------------------------------


def test_activated_ability_splits_cost_from_effect() -> None:
    (ability,) = parse_text("{T}: Add {G}.", "Llanowar Elves").abilities
    assert ability.kind == "activated"
    assert ability.cost == "{T}"
    assert [e.verb for e in ability.effects] == ["add_mana"]


def test_triggered_ability_captures_its_condition() -> None:
    (ability,) = parse_text("Whenever CARD attacks, draw a card.", "CARD").abilities
    assert ability.kind == "triggered"
    assert "attacks" in ability.trigger
    assert [e.verb for e in ability.effects] == ["draw"]


def test_keyword_only_lines_are_not_effects() -> None:
    parsed = parse_text("Flying", "CARD", keywords={"Flying"})
    assert parsed.abilities[0].kind == "keyword"
    assert parsed.effects == ()
    assert parsed.coverage == 1.0


def test_keyword_lists_are_recognised() -> None:
    parsed = parse_text("Flying, vigilance", "CARD", keywords={"Flying", "Vigilance"})
    assert parsed.abilities[0].kind == "keyword"


@pytest.mark.parametrize(
    "line,keyword",
    [
        ("Equip {1}", "Equip"),
        ("Crew 3", "Crew"),
        ("Enchant creature", "Enchant"),
        ("Ward {2}", "Ward"),
        ("Cycling—Pay 1 life.", "Cycling"),
    ],
)
def test_parameterised_keywords_are_keywords_not_gaps(line: str, keyword: str) -> None:
    """These are named rules, not effects. Treating them as unparsed text was
    the single largest source of apparent parser failure."""
    parsed = parse_text(line, "CARD", keywords={keyword})
    assert parsed.abilities[0].kind == "keyword"
    assert parsed.fully_parsed


def test_multi_line_cards_split_into_separate_abilities() -> None:
    parsed = parse_text(
        "Flying\nWhenever CARD attacks, draw a card.\n{T}: Add {U}.",
        "CARD",
        keywords={"Flying"},
    )
    assert [a.kind for a in parsed.abilities] == ["keyword", "triggered", "activated"]


# --- honesty ------------------------------------------------------------


def test_unrecognised_text_is_reported_not_dropped() -> None:
    parsed = parse_text("Xyzzy the frobnicator plugh.", "CARD")
    assert parsed.effects == ()
    assert parsed.unparsed
    assert parsed.coverage == 0.0
    assert not parsed.fully_parsed


def test_nothing_is_ever_silently_dropped() -> None:
    """The property the whole design rests on: every clause is accounted for."""
    text = (
        "Flying\n"
        "When CARD enters, draw a card. Xyzzy plugh.\n"
        "{2}, {T}: CARD deals 2 damage to any target. Frobnicate the widget."
    )
    parsed = parse_text(text, "CARD", keywords={"Flying"})

    # An activation cost is not an effect: it lands on `Ability.cost`, so the
    # three abilities contribute two effects, not three.
    assert [e.verb for e in parsed.effects] == ["draw", "deal_damage"]
    assert parsed.abilities[2].cost == "{2}, {T}"
    assert len(parsed.unparsed) == 2
    assert 0.0 < parsed.coverage < 1.0
    assert parsed.coverage == 0.5


def test_vanilla_cards_count_as_fully_parsed() -> None:
    parsed = parse_text("", "Grizzly Bears")
    assert parsed.coverage == 1.0
    assert parsed.fully_parsed


# --- coverage measurement -----------------------------------------------


def test_measure_accounts_for_every_clause() -> None:
    from manalab.cards.mana import parse_cost
    from manalab.cards.effects import measure
    from manalab.cards.model import Card

    cards = [
        Card("a", "Bolt", parse_cost("{R}"), "Instant",
             oracle_text="Bolt deals 3 damage to any target."),
        Card("b", "Nonsense", parse_cost("{1}"), "Instant",
             oracle_text="Xyzzy plugh frobnicate."),
        Card("c", "Bear", parse_cost("{1}{G}"), "Creature — Bear"),
    ]
    report = measure(cards)

    assert report.cards == 3
    assert report.vanilla == 1
    assert report.fully_parsed == 2  # Bolt and the vanilla Bear
    assert report.matched + sum(report.misses.values()) == report.clauses
    assert report.top_verbs(1)[0][0] == "deal_damage"


def test_measure_collapses_numbers_so_gaps_group() -> None:
    """"deals 3 damage" and "deals 5 damage" are one gap, not two."""
    from manalab.cards.mana import parse_cost
    from manalab.cards.effects import measure
    from manalab.cards.model import Card

    cards = [
        Card(str(n), f"C{n}", parse_cost("{1}"), "Instant",
             oracle_text=f"Xyzzy {n} plugh.")
        for n in (3, 5, 7)
    ]
    report = measure(cards)
    assert len(report.misses) == 1
    assert list(report.misses.values()) == [3]


# --- the parser plan, items 1-5 ------------------------------------------


def test_target_player_draws_carries_its_target():
    """"Target player draws three cards" — the Ancestral Recall class. The
    target used to be residue; now it is a parameter `resolve` re-checks."""
    parsed = parse_text("Target player draws three cards.", "Recall")
    (ability,) = parsed.abilities
    (effect,) = ability.effects
    assert effect.verb == "draw"
    assert str(effect.get("target")).lower() == "target player"
    assert effect.get("amount") == 3
    assert parsed.fully_parsed


def test_target_player_gains_life_carries_its_target():
    parsed = parse_text("Target player gains 4 life.", "Balm")
    (effect,) = parsed.abilities[0].effects
    assert str(effect.get("target")).lower() == "target player"


def test_you_may_draw_is_greedy_yes():
    """A declared approximation: optional self-upside is executed as mandatory,
    because a competent pilot always says yes to its own upside."""
    parsed = parse_text("You may draw a card.", "Chart")
    assert parsed.fully_parsed
    assert parsed.verbs == {"draw"}


def test_another_players_may_is_not_ours_to_take():
    parsed = parse_text("Each opponent may draw a card.", "Trap")
    assert not parsed.fully_parsed


def test_a_loyalty_cost_is_recorded_not_dropped():
    """+1:/−X: lines are activated abilities whose cost is loyalty. 873 of them
    used to parse their body fine and drop the cost on the floor."""
    parsed = parse_text("+1: Draw a card.", "Jace")
    (ability,) = parsed.abilities
    assert ability.kind == "activated"
    assert ability.cost == "+1 loyalty"
    assert ability.effects[0].verb == "draw"

    minus = parse_text("−7: You gain 10 life.", "Jace")
    assert minus.abilities[0].cost == "-7 loyalty"


def test_untap_static_prose_is_not_an_untap_effect():
    """Static Orb's "players can't untap more than two permanents during their
    untap steps" used to become untap(target='more than two permanents…')."""
    parsed = parse_text(
        "Players can't untap more than two permanents during their untap steps.",
        "Static Orb")
    assert "untap" not in parsed.verbs


def test_untap_target_creature_is_an_untap_effect():
    parsed = parse_text("Untap target creature.", "Twiddle")
    (effect,) = parsed.abilities[0].effects
    assert effect.verb == "untap"
    assert effect.get("target") == "target creature"


def test_coverage_counts_clauses_once():
    """"Draw a card, then discard a card" is ONE clause matching two patterns.
    Counting effects put 5,223 phantom matches in both the numerator and the
    denominator, so multi-verb clauses looked better than they were."""
    parsed = parse_text("Draw a card, then discard a card.", "Loot")
    assert len(parsed.effects) == 2
    assert parsed.abilities[0].matched_clauses == 1
    assert parsed.coverage == 1.0
