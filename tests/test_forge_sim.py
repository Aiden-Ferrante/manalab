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
