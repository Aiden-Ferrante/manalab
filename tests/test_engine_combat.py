"""Combat keywords and block assignment.

Synthetic cards throughout, so a failure points at the rules and not at
Scryfall. Every test here drives `combat` directly against a hand-built board
rather than playing a game out, because a keyword bug that only shows up as
"the wrong deck won" is untraceable.
"""

from __future__ import annotations

from manalab.cards.mana import parse_cost
from manalab.cards.model import Card
from manalab.engine import combat, sba
from manalab.engine.state import GameState
from manalab.engine.zones import Zone


def creature(name: str, power: int, toughness: int, *keywords: str) -> Card:
    return Card(
        name.lower().replace(" ", "-"),
        name,
        parse_cost("{1}{G}"),
        "Creature — Test",
        power=str(power),
        toughness=str(toughness),
        keywords=frozenset(keywords),
    )


BEAR = creature("Bear", 2, 2)
GIANT = creature("Giant", 5, 5)
FLYER = creature("Flyer", 2, 2, "Flying")
SPIDER = creature("Spider", 2, 4, "Reach")
SNAKE = creature("Snake", 1, 1, "Deathtouch")
TRAMPLER = creature("Trampler", 5, 5, "Trample")
KNIGHT = creature("Knight", 2, 2, "First strike")
DOUBLE = creature("Doubler", 2, 2, "Double strike")
LEECH = creature("Leech", 3, 3, "Lifelink")
SNEAK = creature("Sneak", 3, 3, "Menace")


def board(attackers: list[Card], blockers: list[Card]) -> GameState:
    """Player 0 attacks player 1 with everything; nothing is blocking yet."""
    state = GameState.new([[], []], seed=0)
    state.active_player = 0
    for card in attackers:
        obj = state.create(card, owner=0, zone=Zone.BATTLEFIELD)
        obj.attacking = 1
    for card in blockers:
        state.create(card, owner=1, zone=Zone.BATTLEFIELD)
    return state


def attackers(state: GameState) -> list:
    return [o for o in state.battlefield() if o.attacking is not None]


def block(state: GameState, blocker_index: int, attacker_index: int) -> None:
    blocker = state.battlefield(1)[blocker_index]
    attacker = attackers(state)[attacker_index]
    blocker.blocking = attacker.id
    attacker.blocked_by = attacker.blocked_by + (blocker.id,)


def strike(state: GameState) -> None:
    """Both damage passes plus state-based actions, as the driver does it."""
    live = attackers(state)
    if combat.any_first_strike(live, state):
        combat.combat_damage(state, live, first_strike_pass=True)
        sba.check(state)
        live = attackers(state)
    combat.combat_damage(state, live, first_strike_pass=False)
    sba.check(state)


def names_on(state: GameState, player: int) -> set[str]:
    return {o.card.name for o in state.battlefield(player)}


# --- evasion ------------------------------------------------------------


def test_ground_creature_cannot_block_a_flyer() -> None:
    state = board([FLYER], [BEAR])
    assert not combat.can_block(state.battlefield(1)[0], attackers(state)[0])


def test_reach_blocks_a_flyer() -> None:
    state = board([FLYER], [SPIDER])
    assert combat.can_block(state.battlefield(1)[0], attackers(state)[0])


def test_a_flyer_blocks_a_flyer() -> None:
    state = board([FLYER], [FLYER])
    assert combat.can_block(state.battlefield(1)[0], attackers(state)[0])


def test_flying_removes_the_pairing_from_enumeration() -> None:
    state = board([FLYER], [BEAR])
    options, _ = combat.legal_blocks(state, 1, [a.id for a in attackers(state)])
    assert options == [()], "a ground blocker was offered a flyer to block"


def test_menace_cannot_be_blocked_by_exactly_one() -> None:
    state = board([SNEAK], [BEAR, GIANT])
    options, _ = combat.legal_blocks(state, 1, [a.id for a in attackers(state)])
    sizes = {len(o) for o in options}
    assert sizes == {0, 2}, f"menace allowed a single blocker: {sizes}"


# --- the multi-blocker fix ----------------------------------------------


def test_two_blockers_can_block_two_different_attackers() -> None:
    """The bug this replaced: only one blocker could ever be declared."""
    state = board([BEAR, GIANT], [BEAR, GIANT])
    ids = [a.id for a in attackers(state)]
    options, _ = combat.legal_blocks(state, 1, ids)

    both = [o for o in options if len(o) == 2 and len({a for _, a in o}) == 2]
    assert both, "no assignment blocks both attackers"


def test_two_blockers_can_gang_up_on_one_attacker() -> None:
    state = board([GIANT], [BEAR, BEAR])
    ids = [a.id for a in attackers(state)]
    options, _ = combat.legal_blocks(state, 1, ids)
    assert any(len(o) == 2 and len({a for _, a in o}) == 1 for o in options)


def test_no_blocks_is_always_offered() -> None:
    state = board([BEAR], [BEAR])
    options, _ = combat.legal_blocks(state, 1, [a.id for a in attackers(state)])
    assert () in options


def test_tapped_creatures_cannot_block() -> None:
    state = board([BEAR], [BEAR])
    state.battlefield(1)[0].tapped = True
    options, _ = combat.legal_blocks(state, 1, [a.id for a in attackers(state)])
    assert options == [()]


def test_wide_boards_truncate_rather_than_explode() -> None:
    state = board([BEAR] * 8, [BEAR] * 8)
    options, truncated = combat.legal_blocks(state, 1, [a.id for a in attackers(state)])
    assert truncated
    assert len(options) <= combat.MAX_BLOCK_OPTIONS
    assert () in options, "truncation must still leave a legal choice"


# --- damage -------------------------------------------------------------


def test_unblocked_damage_hits_the_player() -> None:
    state = board([GIANT], [])
    strike(state)
    assert state.players[1].life == 15


def test_blocked_creature_deals_no_damage_to_the_player() -> None:
    state = board([GIANT], [GIANT])
    block(state, 0, 0)
    strike(state)
    assert state.players[1].life == 20


def test_trample_spills_excess_over_the_blocker() -> None:
    state = board([TRAMPLER], [BEAR])
    block(state, 0, 0)
    strike(state)
    # 2 of 5 is lethal to a 2/2; 3 tramples through.
    assert state.players[1].life == 17


def test_without_trample_excess_is_wasted() -> None:
    state = board([GIANT], [BEAR])
    block(state, 0, 0)
    strike(state)
    assert state.players[1].life == 20


def test_deathtouch_kills_a_far_bigger_creature() -> None:
    state = board([GIANT], [SNAKE])
    block(state, 0, 0)
    strike(state)
    assert "Giant" not in names_on(state, 0), "deathtouch did not kill the giant"
    assert "Snake" not in names_on(state, 1), "the giant did not kill the snake"


def test_deathtouch_plus_trample_only_needs_one_point_for_the_blocker() -> None:
    state = board([creature("Wurm", 5, 5, "Trample", "Deathtouch")], [GIANT])
    block(state, 0, 0)
    strike(state)
    # 1 is lethal from a deathtoucher, so 4 tramples over.
    assert state.players[1].life == 16


def test_first_strike_kills_before_taking_damage() -> None:
    state = board([KNIGHT], [BEAR])
    block(state, 0, 0)
    strike(state)
    assert "Knight" in names_on(state, 0), "the first striker died anyway"
    assert "Bear" not in names_on(state, 1)


def test_first_strike_does_not_save_it_from_something_bigger() -> None:
    state = board([KNIGHT], [GIANT])
    block(state, 0, 0)
    strike(state)
    assert "Knight" not in names_on(state, 0)
    assert "Giant" in names_on(state, 1)


def test_double_strike_deals_damage_in_both_passes() -> None:
    state = board([DOUBLE], [])
    strike(state)
    assert state.players[1].life == 16


def test_lifelink_gains_life_on_player_damage() -> None:
    state = board([LEECH], [])
    strike(state)
    assert state.players[0].life == 23
    assert state.players[1].life == 17


def test_lifelink_gains_life_when_blocked_too() -> None:
    """All 3 power lands on the 2/2 — 2 lethal, 1 excess — so it gains 3, not 2."""
    state = board([LEECH], [BEAR])
    block(state, 0, 0)
    strike(state)
    assert state.players[0].life == 23, "damage dealt to a blocker is still damage"


def test_blocking_lifelinker_gains_life() -> None:
    state = board([BEAR], [LEECH])
    block(state, 0, 0)
    strike(state)
    assert state.players[1].life == 23


def test_damage_is_simultaneous() -> None:
    """A creature that dies still dealt its damage — the classic trade bug."""
    state = board([BEAR], [BEAR])
    block(state, 0, 0)
    strike(state)
    assert names_on(state, 0) == set()
    assert names_on(state, 1) == set()


def test_two_blockers_are_not_enough_to_kill_the_big_attacker() -> None:
    """Four power into a 5/5 is not lethal, and the 5/5 eats both."""
    state = board([GIANT], [BEAR, BEAR])
    block(state, 0, 0)
    block(state, 1, 0)
    strike(state)
    assert "Giant" in names_on(state, 0)
    assert names_on(state, 1) == set(), "5 power is lethal to both 2/2s"


def test_three_blockers_kill_it_and_it_kills_only_what_it_can() -> None:
    state = board([GIANT], [BEAR, BEAR, BEAR])
    for i in range(3):
        block(state, i, 0)
    strike(state)
    assert "Giant" not in names_on(state, 0), "6 power across three blockers is lethal"
    # 5 power: 2 and 2 are lethal to the first two, 1 spills into the third.
    assert len(state.battlefield(1)) == 1
