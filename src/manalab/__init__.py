"""manalab — a deckbuilding search engine that happens to contain a Magic simulator.

See ARCHITECTURE.md. The short version: `manalab.evaluate.Evaluator` is the only
boundary that matters, and `manalab.search` must never import `manalab.game`.
"""

__version__ = "0.1.0"
