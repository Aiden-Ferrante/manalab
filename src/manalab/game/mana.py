"""Mana payment for the goldfish model.

The solver itself lives in `manalab.cards.payment`, because the engine needs the
same logic and the two game models may not import each other. This module exists
so the goldfish code reads in its own vocabulary.
"""

from manalab.cards.payment import Source, assign, can_pay

__all__ = ["Source", "assign", "can_pay"]
