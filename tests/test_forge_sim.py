"""The Forge-backed evaluator: deck format, result parsing, honest availability."""

from __future__ import annotations

import pytest

from manalab.evaluate import forge_sim


def test_dck_format_puts_the_commander_in_its_own_section(tmp_path):
    path = forge_sim.write_dck("t", "Yeva, Nature's Herald",
                               {"Forest": 40, "Yeva, Nature's Herald": 1,
                                "Grizzly Bears": 4}, tmp_path)
    text = path.read_text()
    assert "[Commander]\n1 Yeva, Nature's Herald" in text
    assert "40 Forest" in text
    # The commander is not double-counted into the main board.
    assert "\n1 Yeva" not in text.split("[Main]")[1]


def test_the_result_line_parses():
    line = "Game Result: Game 1 ended in 14094 ms. Ai(1)-cand_x has won!"
    found = forge_sim._GAME_RESULT.search(line)
    assert found and "cand_x" in found.group(1)


def test_three_opponents_exactly():
    with pytest.raises(ValueError):
        forge_sim.ForgeSimEvaluator([("a", "b", {}), ("c", "d", {})])


@pytest.mark.skipif(not forge_sim.available(), reason="Forge not installed")
def test_forge_is_installed_here():
    assert forge_sim.available()


def test_cache_key_is_stable_and_sensitive():
    from manalab.evaluate.forge_sim import _cache_key

    counts = {"Forest": 38, "Grizzly Bears": 4}
    opp = [("a", "X", {"Plains": 40})]
    k1 = _cache_key(counts, "Yeva", opp, 7, 12, 420)
    assert k1 == _cache_key(dict(counts), "Yeva", list(opp), 7, 12, 420)
    assert k1 != _cache_key(counts, "Yeva", opp, 8, 12, 420), "seed must matter"
    assert k1 != _cache_key({**counts, "Forest": 39}, "Yeva", opp, 7, 12, 420)


def test_cache_round_trips(tmp_path, monkeypatch):
    import manalab.evaluate.forge_sim as fs

    monkeypatch.setattr(fs, "_CACHE_DB", tmp_path / "cache.sqlite")
    with fs._cache() as con:
        con.execute("INSERT INTO results VALUES (?, ?)", ("k", "[1.0, 0.0]"))
    with fs._cache() as con:
        row = con.execute("SELECT samples FROM results WHERE key='k'").fetchone()
    assert row[0] == "[1.0, 0.0]"


CAPPED = """
Game Outcome: Turn 20
Game Outcome: Ai(1)-cand_stompy has won because all opponents have lost
Game Outcome: Ai(2)-opp0 has won because all opponents have lost
Game Outcome: Ai(3)-opp1 has won because all opponents have lost
Game Outcome: Ai(4)-opp2 has won because all opponents have lost
Game Result: Game 5 ended in 420001 ms. Ai(2)-opp0 has won!
"""

DECIDED_WIN = """
Game Outcome: Turn 18
Game Outcome: Ai(2)-opp0 has lost because life total reached 0
Game Outcome: Ai(3)-opp1 has lost because life total reached 0
Game Outcome: Ai(4)-opp2 has lost because life total reached 0
Game Outcome: Ai(1)-cand_stompy has won because all opponents have lost
Game Result: Game 3 ended in 16266 ms. Ai(1)-cand_stompy has won!
"""

DECIDED_LOSS = """
Game Outcome: Turn 21
Game Outcome: Ai(1)-cand_stompy has lost because life total reached 0
Game Outcome: Ai(2)-opp0 has won because all opponents have lost
Game Outcome: Ai(3)-opp1 has lost because life total reached 0
Game Outcome: Ai(4)-opp2 has lost because life total reached 0
Game Result: Game 2 ended in 30807 ms. Ai(2)-opp0 has won!
"""


def test_clock_capped_game_is_a_draw_not_an_opponent_win():
    """Forge logs a timed-out game as EVERY player winning, then names one.

    Reading the named player credited a phantom win: measured at a 25s clock,
    8 of 9 capped games were named for seat Ai(2) while the candidate sits in
    seat 1. A draw must be neither a win nor a loss.
    """
    from manalab.evaluate.forge_sim import parse_results

    assert parse_results(CAPPED, "cand_stompy") == [None]
    assert parse_results(DECIDED_WIN, "cand_stompy") == [1.0]
    assert parse_results(DECIDED_LOSS, "cand_stompy") == [0.0]


def test_draws_leave_the_win_rate_and_are_reported():
    from manalab.evaluate.forge_sim import _result, parse_results

    stdout = DECIDED_WIN + CAPPED + DECIDED_LOSS + CAPPED
    played = parse_results(stdout, "cand_stompy")
    assert played == [1.0, None, 0.0, None]

    result = _result("d", "forge-sim", played, seed=1)
    assert result.metrics["win_rate"] == 0.5, "1 of 2 DECIDED games"
    assert result.metrics["draw_rate"] == 0.5
    assert result.metrics["games_played"] == 4.0
    assert result.n_games == 2


def test_parse_version_is_in_the_cache_key():
    """A result stored by the old, wronger parser must not be served."""
    import manalab.evaluate.forge_sim as fs

    key = fs._cache_key({"Forest": 38}, "Yeva", [("a", "X", {"Plains": 40})],
                        7, 12, 420)
    original = fs.PARSE_VERSION
    try:
        fs.PARSE_VERSION = original + 1
        assert fs._cache_key({"Forest": 38}, "Yeva",
                             [("a", "X", {"Plains": 40})], 7, 12, 420) != key
    finally:
        fs.PARSE_VERSION = original
