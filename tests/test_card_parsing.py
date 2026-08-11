"""Scryfall record -> Card. Synthetic rows, so no card store is needed.

The land cases here are the ones that silently wreck results: a shockland
modeled as always-tapped or a fetchland modeled as producing nothing will make
every real constructed deck simulate as worse than it is.
"""

from __future__ import annotations

from manalab.cards.model import card_from_scryfall


def row(name: str, text: str, *, type_line: str = "Land", produced=None, cost=None):
    return {
        "oracle_id": name,
        "name": name,
        "mana_cost": cost,
        "type_line": type_line,
        "oracle_text": text,
        "produced_mana": produced,
    }


def test_basic_land() -> None:
    card = card_from_scryfall(row("Mountain", "({T}: Add {R}.)", produced=["R"]))
    assert card.is_land and card.taps_for_mana
    assert card.produces == {"R"}
    assert not card.enters_tapped


def test_plain_tapland_enters_tapped() -> None:
    card = card_from_scryfall(
        row("Boros Garrison", "Boros Garrison enters tapped.", produced=["R", "W"])
    )
    assert card.enters_tapped


def test_shockland_enters_untapped() -> None:
    """You pay the 2 life. Modeling it as always tapped understates every deck
    that plays one, which in Modern is most of them."""
    card = card_from_scryfall(
        row(
            "Sacred Foundry",
            "({T}: Add {R} or {W}.)\nAs this land enters, you may pay 2 life. "
            "If you don't, it enters tapped.",
            produced=["R", "W"],
        )
    )
    assert card.produces == {"R", "W"}
    assert not card.enters_tapped


def test_checkland_style_condition_enters_untapped() -> None:
    card = card_from_scryfall(
        row(
            "Inspiring Vantage",
            "This land enters tapped unless you control two or fewer other lands.\n"
            "{T}: Add {R} or {W}.",
            produced=["R", "W"],
        )
    )
    assert not card.enters_tapped


def test_fetchland_is_approximated_as_a_dual() -> None:
    """Scryfall reports no produced_mana for a fetch, which is literally true and
    practically useless — it would simulate as a land that does nothing."""
    card = card_from_scryfall(
        row(
            "Arid Mesa",
            "{T}, Pay 1 life, Sacrifice this land: Search your library for a "
            "Mountain or Plains card, put it onto the battlefield, then shuffle.",
        )
    )
    assert card.taps_for_mana
    assert card.produces == {"R", "W"}
    assert not card.enters_tapped


def test_fetchland_that_fetches_tapped() -> None:
    card = card_from_scryfall(
        row(
            "Evolving Wilds",
            "{T}, Sacrifice this land: Search your library for a basic land card, "
            "put it onto the battlefield tapped, then shuffle.",
        )
    )
    # No basic land type named, so there is no color to infer.
    assert not card.taps_for_mana


def test_nonbasic_search_is_not_treated_as_a_fetchland() -> None:
    card = card_from_scryfall(
        row(
            "Expedition Map",
            "{2}, {T}, Sacrifice this: Search your library for a land card, "
            "put it into your hand, then shuffle.",
            type_line="Artifact",
        )
    )
    assert not card.taps_for_mana
    assert card.produces == frozenset()


def test_spell_costs_parse() -> None:
    card = card_from_scryfall(
        row("Boros Charm", "Choose one —", type_line="Instant", cost="{R}{W}")
    )
    assert not card.is_land
    assert card.cmc == 2
    assert card.cost.colors == {"R", "W"}
