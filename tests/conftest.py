"""Shared fixtures.

`data/cards.duckdb` is gitignored and built locally from Scryfall
(`manalab fetch && manalab build`), so a fresh clone does not have it. Tests that
read real cards depend on `cards_db` and skip, rather than error, without it.
"""

from __future__ import annotations

import pytest

from manalab.cards.store import DEFAULT_DB


@pytest.fixture(scope="session")
def cards_db():
    if not DEFAULT_DB.exists():
        pytest.skip(f"{DEFAULT_DB} not built — run `manalab fetch && manalab build`")
    return DEFAULT_DB
