"""Payment solver tests. These are the ones that matter — every mana-base
conclusion the tool produces is downstream of `assign` being correct."""

from __future__ import annotations

from manalab.cards.mana import parse_cost
from manalab.cards.payment import assign, can_pay

W, U, B, R, G = (frozenset(c) for c in "WUBRG")
WU = frozenset("WU")
COLORLESS = frozenset()


def test_parse_basic_cost() -> None:
    cost = parse_cost("{2}{W}{W}")
    assert cost.generic == 2
    assert cost.cmc == 4
    assert cost.pips == 2
    assert cost.pip_count("W") == 2


def test_parse_hybrid_accepts_either_color() -> None:
    cost = parse_cost("{W/U}")
    assert cost.symbols == (WU,)
    # A hybrid symbol does not *require* either color.
    assert cost.pip_count("W") == 0
    assert can_pay(cost, [U])


def test_parse_x_and_lands() -> None:
    assert parse_cost("{X}{R}").x_count == 1
    assert parse_cost("{X}{R}").cmc == 1  # X counts as zero, as in the real rules
    assert parse_cost(None).cmc == 0


def test_phyrexian_is_flagged_as_approximated() -> None:
    assert parse_cost("{W/P}").approximated


def test_one_dual_cannot_satisfy_two_different_pips() -> None:
    """The case a naive per-color source counter gets wrong.

    For {W}{U} with a W/U dual and a Mountain: counting colors independently
    sees one white source and one blue source and two total lands, and says
    yes. But the dual taps once, and the Mountain pays neither pip.
    """
    assert not can_pay(parse_cost("{W}{U}"), [WU, R])
    # It works as soon as one real source of either color joins it.
    assert can_pay(parse_cost("{W}{U}"), [WU, W])
    # Two duals genuinely do cover both {W}{U} and {W}{W}.
    assert can_pay(parse_cost("{W}{U}"), [WU, WU])
    assert can_pay(parse_cost("{W}{W}"), [WU, WU])


def test_generic_paid_by_anything_including_colorless() -> None:
    assert can_pay(parse_cost("{2}{R}"), [R, COLORLESS, COLORLESS])
    assert not can_pay(parse_cost("{2}{R}"), [COLORLESS, COLORLESS, COLORLESS])


def test_insufficient_sources() -> None:
    assert not can_pay(parse_cost("{3}"), [R, R])


def test_assign_returns_exactly_cmc_sources_and_leaves_the_rest() -> None:
    sources = [W, U, R, R, COLORLESS]
    used = assign(parse_cost("{1}{U}"), sources)
    assert used is not None
    assert len(used) == 2
    # The blue source must be among those spent; three sources stay untapped.
    assert any(sources[i] == U for i in used)
    assert len(set(range(len(sources))) - set(used)) == 3


def test_generic_prefers_the_least_flexible_leftover() -> None:
    """Paying generic with a colorless source keeps the dual free for later."""
    sources = [WU, COLORLESS]
    used = assign(parse_cost("{1}"), sources)
    assert used == (1,)


def test_zero_cost_is_free() -> None:
    assert assign(parse_cost("{0}"), []) == ()
