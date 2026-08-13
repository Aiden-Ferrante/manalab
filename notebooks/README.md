# Notebooks

Executed walkthroughs of manalab, in dependency order. Every notebook is stored
**with its outputs**, so it reads without running anything — but all of them run
end to end, and re-running is the point.

```bash
uv pip install -e '.[dev,notebooks]'
jupyter lab notebooks/
```

Each notebook finds the repo root by walking up from the working directory, so it
does not matter where you launch Jupyter from. They need `data/cards.duckdb`,
which is a build artifact: `manalab fetch && manalab build` if it is missing.

## `cards/` — where card data comes from

| | |
|---|---|
| [`01-the-card-database`](cards/01-the-card-database.ipynb) | Scryfall ingest, the five tables, power/toughness as strings, and **faces** — the structural decision that caused the most bugs. |
| [`02-classifying-cards`](cards/02-classifying-cards.ipynb) | Oracle text into `Effect(verb, params)`. What the parser produces (67 verbs) versus what the engine executes (5). The target language, and why it refuses 355 phrases. |
| [`03-retrieval-and-pools`](cards/03-retrieval-and-pools.ipynb) | Getting cards back out: the store API, SQL, colour identity vs colour, oracle tags, and building a `CandidatePool` split by fidelity. |

## `engine/` — how a game of Magic runs

| | |
|---|---|
| [`01-objects-and-zones`](engine/01-objects-and-zones.ipynb) | `Card` vs `GameObject`, the seven zones, and `move` — the only mutation. Why a zone change mints a new id (CR 400.7) and a stale reference raises. |
| [`02-turns-priority-and-the-stack`](engine/02-turns-priority-and-the-stack.ipynb) | Twelve steps, sorcery-speed timing, the priority loop, the stack, and state-based actions. Ends by showing that an agent *cannot* make an illegal play. |
| [`03-combat`](engine/03-combat.ipynb) | Attacking, blocking legality, multi-blocker assignment, and damage — trample, deathtouch, first strike, lifelink. Which keywords actually move a win rate. |
| [`04-spells-and-targeting`](engine/04-spells-and-targeting.ipynb) | Casting, choosing targets, resolving verbs, and `fidelity` — the engine's account of its own blind spots. |

## Top level — what it is all for

| | |
|---|---|
| [`genetic_deck_search`](genetic_deck_search.ipynb) | The payoff: a genetic algorithm over decklists scored by real games, with the winner's-curse correction and a held-out gauntlet check. |

## Reading order

If you want the whole path in one sitting: `cards/01 → cards/02 → engine/01 →
engine/02 → engine/03 → engine/04 → cards/03 → genetic_deck_search`.

`cards/03` sits late on purpose — the fidelity split only makes sense once you
have seen what the engine can and cannot execute.

## A note on the tone

These notebooks are as interested in what the engine *cannot* do as in what it
can. That is not modesty: a rules engine that quietly approximates a card it does
not understand produces games that look completely reasonable and are wrong, and
a deck search on top of it will find and exploit every one of those gaps. Each
notebook ends with the honest list.
