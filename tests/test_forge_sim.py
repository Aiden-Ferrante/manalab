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
