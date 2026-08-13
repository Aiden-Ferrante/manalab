# Reports

Experiment output. **Read the replication status before believing any of it.**

## Replicated — trustworthy

| File | What it says |
|---|---|
| `replicates.txt` | 4 seeds × 2 gauntlet conditions. Seed-to-seed noise on the five-colour spread is **±0.116**. Adding sweepers to the gauntlet changed it by **−0.006**, i.e. not at all. Surviving claims: black strongest (0.69 ± 0.06), blue weakest (0.26 ± 0.07); the middle three are *not* ordered by the data. |

## Single-run — retracted

These were produced one seed at a time, before the noise floor was measured. The
differences between them are all smaller than ±0.116, so the apparent trend
across them — a colour spread of 0.538 → 0.527 → 0.412 → 0.379 → 0.609, narrated
at the time as verbs opening the metagame and sweepers closing it — **is noise**.

| File | Gauntlet |
|---|---|
| `colors-with-spells.txt` | creature-only archetypes, engine with effect verbs |
| `colors-spell-gauntlet.txt` | burn and removal archetypes added |
| `colors-counterspells.txt` | counterspells added to the removal archetype |
| `colors-sweepers.txt` | sweepers preferred by the removal archetype |

Kept as a record of the mistake rather than deleted. Reproduce any of them with
`examples/evolve_all_colors.py`, which now replicates by default and prints tiers
instead of a ranking.

## Co-evolution

| File | What it says |
|---|---|
| `coevo-before-verbs.txt` | 5 rounds, engine with no effect verbs |
| `coevo-after-verbs.txt` | 5 rounds, same script and seed, verbs implemented |

Diff them with `examples/compare_coevolution.py`. Also single-run, so the
*magnitudes* carry the same caveat — but two structural observations do not
depend on effect size: no champion from the final round ever holds Nash weight,
and before verbs every intransitive triple ran through two zero-weight decks
while after verbs the cycles involve decks that carry weight.

## Other

| File | What it says |
|---|---|
| `audit_effects.md` | Effect-parser precision audit, for a human to mark up. |
